import re
import json
import asyncio
import logging
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

import httpx

from app.services.scraper.base import BaseScraper
from app.schemas.scraper import MediaItem, MediaType

logger = logging.getLogger(__name__)

# Regex: lh3 URLs with /pw/ path (album photos only, excludes /a/ profile pics)
_LH3_PHOTO_RE = re.compile(
    r'(https://lh3\.googleusercontent\.com/pw/[A-Za-z0-9_\-/]+(?:=[^\s"\'\\,\])}]+)?)'
)

# AF_initDataCallback blocks contain Google's embedded data as JS arrays.
# We extract the 'data' field from each callback.
_AF_DATA_RE = re.compile(
    r"AF_initDataCallback\(\s*\{.*?data:\s*(\[[\s\S]*?\])\s*\}\s*\)\s*;",
)

# ── RPC 페이지 수집 (초기 HTML은 300개까지만 내장) ──────────────────────────
# 공유앨범 페이지의 ds:1 데이터 블록: data[1]=항목 목록, data[2]=다음 페이지
# 토큰, data[3][19]=RPC 인증 키(base64 문자열 그대로 사용해야 함).
_DS1_RE = re.compile(
    r"AF_initDataCallback\(\{key: 'ds:1'.*?data:(\[.*?\]), sideChannel",
    re.DOTALL,
)
_BATCHEXECUTE_URL = "https://photos.google.com/_/PhotosUi/data/batchexecute"
# batchexecute 응답에서 snAcKc 결과(이스케이프된 JSON 문자열) 추출
_RPC_RESULT_RE = re.compile(
    r'\[\["wrb\.fr","snAcKc","(.*)"\s*,\s*null,\s*null,\s*null,\s*"generic"\]',
    re.DOTALL,
)
# 항목 dict에 이 키가 있으면 동영상 (duration ms·해상도 포함)
_VIDEO_MARKER_KEY = "76647426"
_MAX_RPC_PAGES = 40  # 안전 상한 ≈ 12,000장
_RPC_TIMEOUT = 15.0


def _parse_ds1(html: str) -> tuple[list, str | None, str | None] | None:
    """ds:1 블록에서 (항목 목록, 다음 페이지 토큰, RPC 인증 키)를 추출.

    구조가 예상과 다르면 None — 호출부는 정규식-단독 수집(초기 300장)으로 강등.
    """
    m = _DS1_RE.search(html)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
        items = data[1] if isinstance(data[1], list) else []
        token = data[2] if isinstance(data[2], str) and data[2] else None
        auth_key = None
        meta = data[3]
        if isinstance(meta, list) and len(meta) > 19 and isinstance(meta[19], str):
            auth_key = meta[19]
        return items, token, auth_key
    except (json.JSONDecodeError, IndexError, TypeError):
        return None


def _share_id_from_url(final_url: str) -> str | None:
    m = re.search(r"/share/([^/?#]+)", final_url)
    return m.group(1) if m else None


def _bases_from_items(items: list) -> dict[str, bool]:
    """ds:1/RPC 항목 목록 → {base URL: 동영상 여부}."""
    result: dict[str, bool] = {}
    for item in items:
        try:
            url = item[1][0]
        except (TypeError, IndexError, KeyError):
            continue
        if not isinstance(url, str) or "lh3.googleusercontent.com/pw/" not in url:
            continue
        base = url.split("=")[0] if "=" in url else url
        meta = item[-1] if isinstance(item[-1], dict) else {}
        result[base] = _VIDEO_MARKER_KEY in meta
    return result


async def _fetch_album_page(
    client: httpx.AsyncClient,
    share_id: str,
    token: str,
    auth_key: str,
) -> tuple[list, str | None]:
    """batchexecute RPC(snAcKc)로 공유앨범 다음 페이지를 수집.

    실패 시 ([], None) — 호출부 루프가 중단되고 수집분은 유지된다.
    """
    try:
        freq = json.dumps(
            [[["snAcKc", json.dumps([share_id, token, None, auth_key]), None, "generic"]]]
        )
        resp = await client.post(
            _BATCHEXECUTE_URL,
            data={"f.req": freq},
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
            timeout=_RPC_TIMEOUT,
        )
        m = _RPC_RESULT_RE.search(resp.text)
        if not m:
            logger.warning("GooglePhotos RPC: unexpected response (status=%s)", resp.status_code)
            return [], None
        # 결과는 JSON 문자열로 이스케이프되어 있음 → 이중 json.loads
        inner = json.loads(json.loads(f'"{m.group(1)}"'))
        items = inner[1] if len(inner) > 1 and isinstance(inner[1], list) else []
        next_token = (
            inner[2] if len(inner) > 2 and isinstance(inner[2], str) and inner[2] else None
        )
        return items, next_token
    except (httpx.HTTPError, json.JSONDecodeError, IndexError, TypeError) as e:
        logger.warning("GooglePhotos RPC page fetch failed: %s", e)
        return [], None


def _extract_og_image_base(html: str) -> str | None:
    """og:image 메타태그에서 앨범 커버의 base URL(사이즈 접미사 제외)을 추출.

    공유 페이지 헤더 이미지 = 앨범 커버라서 스크랩 목록 첫 항목이 항상 커버가 된다.
    base URL 매칭으로 해당 항목을 is_cover 로 표시하기 위해 사용.
    """
    for pattern in (
        r'<meta\s+[^>]*property=["\']og:image["\']\s+[^>]*content=["\']([^"\']*)["\']',
        r'<meta\s+[^>]*content=["\']([^"\']*)["\']\s+[^>]*property=["\']og:image["\']',
    ):
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            url = match.group(1).strip()
            return url.split("=")[0] if "=" in url else url
    return None


def _ensure_desktop_redirect(url: str) -> str:
    """Append ?_imcp=1 to photos.app.goo.gl URLs to trigger server-side redirect
    to photos.google.com instead of the Firebase Dynamic Link page."""
    if "photos.app.goo.gl" in url:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if "_imcp" not in qs:
            qs["_imcp"] = ["1"]
            new_query = urlencode(qs, doseq=True)
            return urlunparse(parsed._replace(query=new_query))
    return url


def _detect_videos_from_html(html: str, base_hashes: dict[str, str]) -> set[str]:
    """Detect video base URLs by scanning HTML context around each URL hash.

    Google Photos embeds media metadata in JavaScript data structures.
    Video items have markers like "VIDEO", "LIVE_PHOTO", video MIME types,
    or duration values near their URL hashes.

    Returns set of base URLs that are likely videos.
    """
    video_bases: set[str] = set()

    # Strategy 1: Search for video markers near each URL hash in the raw HTML
    for base in base_hashes:
        # Extract the unique hash portion (last path segment after /pw/)
        hash_part = base.rsplit("/", 1)[-1] if "/pw/" in base else ""
        if len(hash_part) < 10:
            continue

        for m in re.finditer(re.escape(hash_part), html):
            # Check a window of ~500 chars around the match for video indicators
            start = max(0, m.start() - 300)
            end = min(len(html), m.end() + 500)
            ctx = html[start:end]

            if re.search(
                r'"VIDEO"|"LIVE_PHOTO"|"MOTION_PHOTO"|'
                r'"video/mp4"|"video/webm"|"video/quicktime"|'
                r'video\\?/mp4|video\\?/webm',
                ctx,
            ):
                video_bases.add(base)
                logger.info(
                    "HTML video detected: %s", base[-40:],
                )
                break

    # Strategy 2: Parse AF_initDataCallback blocks for structured data
    if not video_bases:
        _detect_from_af_callbacks(html, base_hashes, video_bases)

    return video_bases


def _detect_from_af_callbacks(
    html: str,
    base_hashes: dict[str, str],
    video_bases: set[str],
) -> None:
    """Try to parse AF_initDataCallback data blocks for video type indicators.

    Google Photos embeds media data in nested arrays. Video items typically
    have a type field set to 2 or 3 (vs 1 for images), or contain
    video-related metadata like duration.
    """
    for match in _AF_DATA_RE.finditer(html):
        raw_data = match.group(1)
        try:
            data = json.loads(raw_data)
        except (json.JSONDecodeError, ValueError):
            continue

        # Walk the parsed data looking for lh3 URLs paired with video indicators
        _walk_data_for_videos(data, base_hashes, video_bases)


def _walk_data_for_videos(
    node: object,
    base_hashes: dict[str, str],
    video_bases: set[str],
    _depth: int = 0,
) -> None:
    """Recursively walk parsed JSON data looking for arrays that contain
    an lh3 URL and nearby video type indicators."""
    if _depth > 15 or not isinstance(node, list):
        return

    # Check if this array contains an lh3 URL string
    lh3_url = None
    has_video_marker = False
    for item in node:
        if isinstance(item, str) and "lh3.googleusercontent.com/pw/" in item:
            base = item.split("=")[0] if "=" in item else item
            if base in base_hashes:
                lh3_url = base
        elif isinstance(item, str) and item.upper() in (
            "VIDEO", "LIVE_PHOTO", "MOTION_PHOTO",
        ):
            has_video_marker = True
        elif isinstance(item, str) and item.startswith("video/"):
            has_video_marker = True

    if lh3_url and has_video_marker:
        video_bases.add(lh3_url)
        logger.info("AF_initDataCallback video detected: %s", lh3_url[-40:])
        return

    # Recurse into sub-arrays
    for item in node:
        if isinstance(item, list):
            _walk_data_for_videos(item, base_hashes, video_bases, _depth + 1)


class GooglePhotosScraper(BaseScraper):
    _PROBE_CONCURRENCY = 10
    _PROBE_TIMEOUT = 5.0

    async def _probe_media_type(
        self,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        base_url: str,
    ) -> tuple[str, MediaType]:
        """Probe base_url=dv to detect video vs image.

        Uses streaming GET (not HEAD) because some CDNs return different
        Content-Type for HEAD requests.  The response body is never read,
        so no bandwidth is wasted.
        """
        probe_url = base_url + "=dv"
        async with semaphore:
            try:
                async with client.stream(
                    "GET",
                    probe_url,
                    follow_redirects=True,
                    timeout=self._PROBE_TIMEOUT,
                ) as resp:
                    ct = resp.headers.get("content-type", "")
                    if resp.status_code == 200 and ct.startswith("video/"):
                        logger.info(
                            "Probe VIDEO: %s (ct=%s)", base_url[-40:], ct,
                        )
                        return (base_url, MediaType.VIDEO)
            except (httpx.TimeoutException, httpx.HTTPError):
                pass
        return (base_url, MediaType.IMAGE)

    async def scrape(self, url: str, progress_callback=None, images_only: bool = False) -> list[MediaItem]:
        fetch_url = _ensure_desktop_redirect(url)

        if progress_callback:
            progress_callback({"step": "fetching_page"})

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=30.0,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            },
        ) as client:
            # Phase 1: HTML fetch + URL extraction
            resp = await client.get(fetch_url)
            resp.raise_for_status()
            html = resp.text

            # 앨범 커버(og:image) base — 목록에서 커버 항목 표시용
            og_cover_base = _extract_og_image_base(html)

            raw_urls = _LH3_PHOTO_RE.findall(html)

            # Phase 2: deduplicate by base URL, collect all param variants
            seen_bases: dict[str, list[str]] = {}  # base -> all source URLs
            for src in raw_urls:
                base = src.split("=")[0] if "=" in src else src
                if base not in seen_bases:
                    seen_bases[base] = []
                seen_bases[base].append(src)

            # Phase 2.5: ds:1 구조 파싱 + RPC 페이지 수집.
            # 초기 HTML에는 앞 300개만 내장되므로, 페이지 토큰이 있으면
            # batchexecute RPC로 나머지를 이어서 수집한다. 항목 구조에서
            # 동영상 여부도 직접 판별(structured_types)해 프로빙을 대체한다.
            # ds:1 파싱이 실패하면 기존 정규식-단독 동작으로 강등.
            structured_types: dict[str, MediaType] = {}
            rpc_pages = 0
            ds1 = _parse_ds1(html)
            if ds1:
                items, token, auth_key = ds1
                for base, is_video in _bases_from_items(items).items():
                    structured_types[base] = (
                        MediaType.VIDEO if is_video else MediaType.IMAGE
                    )
                    if base not in seen_bases:
                        seen_bases[base] = [base]

                share_id = _share_id_from_url(str(resp.url))
                while token and auth_key and share_id and rpc_pages < _MAX_RPC_PAGES:
                    rpc_pages += 1
                    page_items, token = await _fetch_album_page(
                        client, share_id, token, auth_key
                    )
                    if not page_items:
                        break
                    for base, is_video in _bases_from_items(page_items).items():
                        structured_types[base] = (
                            MediaType.VIDEO if is_video else MediaType.IMAGE
                        )
                        if base not in seen_bases:
                            seen_bases[base] = [base]
                    if progress_callback:
                        progress_callback(
                            {"step": "urls_found", "count": len(seen_bases)}
                        )
                if token and rpc_pages >= _MAX_RPC_PAGES:
                    logger.warning(
                        "GooglePhotos RPC: page cap %d reached, album truncated",
                        _MAX_RPC_PAGES,
                    )

            if not seen_bases:
                return []

            if progress_callback:
                progress_callback({"step": "urls_found", "count": len(seen_bases)})

            # Phase 3a: video detection.
            # 구조적 판별(ds:1/RPC)이 성공했으면 그대로 사용하고, 실패한 경우에만
            # 기존 HTML 근접 탐색으로 폴백한다.
            if structured_types:
                type_map: dict[str, MediaType] = dict(structured_types)
            else:
                html_video_bases = _detect_videos_from_html(html, seen_bases)

                # Diagnostic: if no videos found by HTML parsing, dump context
                # around the first URL to help debug the HTML structure
                if not html_video_bases:
                    first_base = next(iter(seen_bases))
                    hash_part = first_base.rsplit("/", 1)[-1] if "/pw/" in first_base else ""
                    if hash_part:
                        idx = html.find(hash_part)
                        if idx >= 0:
                            sample = html[max(0, idx - 100):idx + len(hash_part) + 200]
                            logger.info(
                                "HTML sample near first URL (no videos detected):\n%s",
                                sample,
                            )

                type_map = {b: MediaType.VIDEO for b in html_video_bases}

            # Phase 3b: URL probing for items without a structured/HTML verdict
            undetected = {b for b in seen_bases if b not in type_map}

            if undetected and images_only:
                # 이미지 전용: 네트워크 프로빙 생략 (속도↑). HTML로 감지된 영상만
                # 제외하고, 나머지는 이미지로 간주. HTML에 안 잡힌 일부 영상이
                # 이미지로 섞일 수 있으나 배경 그리드 용도라 허용.
                for b in undetected:
                    type_map[b] = MediaType.IMAGE
            elif undetected:
                semaphore = asyncio.Semaphore(self._PROBE_CONCURRENCY)
                tasks = [
                    self._probe_media_type(client, semaphore, b)
                    for b in undetected
                ]
                total_probes = len(tasks)
                for i, coro in enumerate(asyncio.as_completed(tasks)):
                    base_url, mtype = await coro
                    type_map[base_url] = mtype
                    if progress_callback:
                        progress_callback({"step": "probing_media", "current": i + 1, "total": total_probes})

        # Phase 4: build MediaItem list
        if progress_callback:
            progress_callback({"step": "building_list"})
        media_items: list[MediaItem] = []
        for base, srcs in seen_bases.items():
            media_type = type_map.get(base, MediaType.IMAGE)

            # Fallback: URL parameter check (=m indicates video encoding).
            # 구조적 판별(ds:1)로 이미지가 확정된 항목에는 적용하지 않는다.
            if media_type == MediaType.IMAGE and base not in structured_types:
                if any("=m" in s for s in srcs):
                    media_type = MediaType.VIDEO

            thumbnail_url = base + "=w400-h400"
            original_url = (
                (base + "=dv") if media_type == MediaType.VIDEO
                else (base + "=w2000-h2000")
            )
            media_items.append(
                MediaItem(
                    type=media_type,
                    thumbnail_url=thumbnail_url,
                    original_url=original_url,
                    is_cover=(og_cover_base is not None and base == og_cover_base),
                )
            )

        logger.info(
            "GooglePhotosScraper: %d URLs (%d RPC pages), %d videos detected",
            len(media_items),
            rpc_pages,
            sum(1 for m in media_items if m.type == MediaType.VIDEO),
        )
        return media_items
