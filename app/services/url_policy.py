"""서버가 다운로드해도 되는 미디어 원본 호스트 정책 (SSRF 가드).

api/v1/scraper.py의 프록시 allowlist(_proxy_cache_policy)와 같은 도메인 집합을
공유한다 — 스크래퍼가 생성하는 미디어 도메인 + 구글포토 피커 도메인만 허용.
목록을 바꿀 때는 두 곳을 함께 갱신할 것.
"""

from urllib.parse import urlparse

from app.config import settings

_R2_HOST = (
    urlparse(settings.R2_PUBLIC_URL).netloc.lower()
    if settings.R2_PUBLIC_URL
    else None
)

_ALLOWED_HOSTS = {
    "lh3.googleusercontent.com",
    "drive.google.com",
    "photo.mybox.naver.com",
}
_ALLOWED_SUFFIXES = (
    ".icloud-content.com",
    ".googleusercontent.com",  # 피커 API baseUrl (lh3 외 서브도메인 포함)
)


def is_allowed_media_host(url: str) -> bool:
    """서버 측 다운로드가 허용된 원본인지 검사."""
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    if not host:
        return False
    if _R2_HOST and host == _R2_HOST:
        return True
    if host in _ALLOWED_HOSTS:
        return True
    return any(host.endswith(suffix) for suffix in _ALLOWED_SUFFIXES)


def is_r2_url(url: str) -> bool:
    """자체 R2 공개 URL인지 검사 (upload 소스 검증용)."""
    return bool(
        settings.R2_PUBLIC_URL and url.startswith(settings.R2_PUBLIC_URL)
    )
