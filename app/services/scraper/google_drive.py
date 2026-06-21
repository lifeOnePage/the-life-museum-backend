"""Google Drive 공개 폴더 스크래퍼.

자격증명(API 키) 없이 공개 공유 폴더 페이지의 HTML에 임베드된 파일 목록을
파싱해서 각 파일의 썸네일/원본 URL을 구성한다.

GooglePhotosScraper 와 동일하게 Selenium 없이 httpx 만으로 동작하며,
BaseScraper 의 scrape() 계약을 구현해 다른 스크래퍼들과 동일한
list[MediaItem] 을 반환한다.

현재 image 타입만 수집한다. Drive 영상의 직접 스트리밍 원본 URL 은
제약이 있어(/preview 임베드 필요) 다른 스크래퍼의 재생 가능한 original_url
형식과 호환되지 않기 때문이다. video 분기는 추후 활성화를 위해 보존한다.
"""
import re
import json
import logging
from urllib.parse import urlparse

import httpx

from app.services.scraper.base import BaseScraper
from app.schemas.scraper import MediaItem, MediaType

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# 폴더 페이지에 임베드되는 캐노니컬 파일 목록 블롭
#   window['_DRIVE_ivd'] = '...escaped json...';
_DRIVE_IVD_RE = re.compile(
    r"window\['_DRIVE_ivd'\]\s*=\s*'((?:[^'\\]|\\.)*)'",
)

# 폴백: GooglePhotosScraper 와 동일한 AF_initDataCallback 데이터 블록
_AF_DATA_RE = re.compile(
    r"AF_initDataCallback\(\s*\{.*?data:\s*(\[[\s\S]*?\])\s*\}\s*\)\s*;",
)


def extract_folder_id(url: str) -> str | None:
    """URL 에서 Drive 폴더 ID 추출."""
    m = re.search(r"/folders/([a-zA-Z0-9_-]+)", url)
    if m:
        return m.group(1)
    # ?id=... 형태도 대응
    qs = urlparse(url).query
    m = re.search(r"(?:^|&)id=([a-zA-Z0-9_-]+)", qs)
    return m.group(1) if m else None


def _js_unescape(s: str) -> str:
    """_DRIVE_ivd 의 JS 문자열 이스케이프(\\xNN, \\uNNNN, \\n 등)를 해제."""
    # \/ 는 JS 전용 이스케이프라 unicode_escape 가 모름(경고 발생) → 먼저 치환.
    # 파이썬의 unicode_escape 는 latin-1 가정이라 멀티바이트가 깨질 수 있으므로
    # \/ 정리 후 round-trip 으로 마무리한다.
    s = s.replace("\\/", "/")
    try:
        return s.encode("utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        # 최후 폴백: 흔한 시퀀스만 수동 치환
        return (
            s.replace("\\x22", '"')
            .replace("\\x5b", "[")
            .replace("\\x5d", "]")
            .replace("\\/", "/")
            .replace('\\"', '"')
        )


def _walk_for_files(node, out: list[dict], _depth: int = 0) -> None:
    """중첩 배열을 워킹하며 [id, ?, name, mime, ...] 형태의 파일 엔트리를 수집.

    Drive 파일 엔트리는 흔히 인덱스 0=fileId, 2=name, 3=mimeType 패턴을 가진다.
    구조가 비공식이므로 '문자열 id + mime처럼 보이는 값'을 휴리스틱으로 찾는다.
    """
    if _depth > 25 or not isinstance(node, list):
        return

    # 이 배열 자체가 파일 엔트리인지 검사
    if len(node) >= 4 and isinstance(node[0], str):
        file_id = node[0]
        mime = next(
            (
                x
                for x in node[:6]
                if isinstance(x, str) and "/" in x and (
                    x.startswith("image/")
                    or x.startswith("video/")
                    or x.startswith("application/")
                    or x == "application/vnd.google-apps.folder"
                )
            ),
            None,
        )
        name = node[2] if isinstance(node[2], str) else None
        if (
            mime
            and re.fullmatch(r"[a-zA-Z0-9_-]{20,}", file_id)
        ):
            out.append({"id": file_id, "name": name, "mime": mime})

    for item in node:
        if isinstance(item, list):
            _walk_for_files(item, out, _depth + 1)


def parse_drive_ivd(html: str) -> list[dict]:
    """window['_DRIVE_ivd'] 블롭에서 파일 목록을 추출."""
    m = _DRIVE_IVD_RE.search(html)
    if not m:
        return []
    raw = _js_unescape(m.group(1))
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return []
    out: list[dict] = []
    _walk_for_files(data, out)
    return _dedupe(out)


def parse_af_callbacks(html: str) -> list[dict]:
    """폴백: AF_initDataCallback 데이터 블록에서 파일 목록을 추출."""
    out: list[dict] = []
    for match in _AF_DATA_RE.finditer(html):
        try:
            data = json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            continue
        _walk_for_files(data, out)
    return _dedupe(out)


def _dedupe(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for it in items:
        if it["id"] not in seen:
            seen.add(it["id"])
            result.append(it)
    return result


def classify(mime: str) -> str | None:
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    return None  # 폴더/문서 등은 미디어 아님


def build_urls(file_id: str, media_type: str) -> dict:
    """썸네일/원본 URL 구성."""
    thumbnail = f"https://drive.google.com/thumbnail?id={file_id}&sz=w400"
    if media_type == "video":
        # 직접 스트리밍은 제약이 있어 임베드 preview URL 을 원본으로 둔다
        original = f"https://drive.google.com/file/d/{file_id}/preview"
    else:
        original = f"https://lh3.googleusercontent.com/d/{file_id}=w2000"
    return {"thumbnail_url": thumbnail, "original_url": original}


class GoogleDriveScraper(BaseScraper):
    async def scrape(self, url: str, progress_callback=None) -> list[MediaItem]:
        folder_id = extract_folder_id(url)
        if not folder_id:
            logger.warning("GoogleDriveScraper: folder id 추출 실패 url=%s", url)
            return []

        if progress_callback:
            progress_callback({"step": "fetching_page"})

        page_url = f"https://drive.google.com/drive/folders/{folder_id}"
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=30.0,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            resp = await client.get(page_url)
            resp.raise_for_status()
            html = resp.text

        # 파일 목록 파싱 (_DRIVE_ivd → AF_initDataCallback 폴백)
        files = parse_drive_ivd(html)
        if not files:
            files = parse_af_callbacks(html)

        if not files:
            # 비공개 폴더이거나 로그인 요구 / HTML 구조 변경 가능성.
            # 다른 스크래퍼와 마찬가지로 빈 리스트를 반환한다.
            logger.warning(
                "GoogleDriveScraper: 파일 목록을 찾지 못함 "
                "(비공개 폴더/로그인 요구/구조 변경 가능) folder_id=%s",
                folder_id,
            )
            return []

        if progress_callback:
            progress_callback({"step": "urls_found", "count": len(files)})

        # image 타입만 수집 (video 는 현재 미지원)
        media_items: list[MediaItem] = []
        for f in files:
            if classify(f["mime"]) != "image":
                continue
            urls = build_urls(f["id"], "image")
            media_items.append(
                MediaItem(
                    type=MediaType.IMAGE,
                    thumbnail_url=urls["thumbnail_url"],
                    original_url=urls["original_url"],
                )
            )

        if progress_callback:
            progress_callback({"step": "building_list"})

        logger.info(
            "GoogleDriveScraper: %d files parsed, %d images collected (folder_id=%s)",
            len(files), len(media_items), folder_id,
        )
        return media_items
