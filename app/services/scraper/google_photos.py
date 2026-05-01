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

    async def scrape(self, url: str) -> list[MediaItem]:
        fetch_url = _ensure_desktop_redirect(url)

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

            raw_urls = _LH3_PHOTO_RE.findall(html)

            # Phase 2: deduplicate by base URL, collect all param variants
            seen_bases: dict[str, list[str]] = {}  # base -> all source URLs
            for src in raw_urls:
                base = src.split("=")[0] if "=" in src else src
                if base not in seen_bases:
                    seen_bases[base] = []
                seen_bases[base].append(src)

            if not seen_bases:
                return []

            # Phase 3a: HTML-based video detection (fast, no network)
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

            # Phase 3b: URL probing for items not already detected as video
            # Skip probing entirely if HTML detection found results (saves network)
            undetected = {
                b for b in seen_bases if b not in html_video_bases
            }
            type_map: dict[str, MediaType] = {
                b: MediaType.VIDEO for b in html_video_bases
            }

            if undetected:
                semaphore = asyncio.Semaphore(self._PROBE_CONCURRENCY)
                tasks = [
                    self._probe_media_type(client, semaphore, b)
                    for b in undetected
                ]
                results = await asyncio.gather(*tasks)
                for base_url, mtype in results:
                    type_map[base_url] = mtype

        # Phase 4: build MediaItem list
        media_items: list[MediaItem] = []
        for base, srcs in seen_bases.items():
            media_type = type_map.get(base, MediaType.IMAGE)

            # Fallback: URL parameter check (=m indicates video encoding)
            if media_type == MediaType.IMAGE:
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
                )
            )

        logger.info(
            "GooglePhotosScraper: %d URLs, %d videos detected",
            len(media_items),
            sum(1 for m in media_items if m.type == MediaType.VIDEO),
        )
        return media_items
