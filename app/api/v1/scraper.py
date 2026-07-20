import logging
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import StreamingResponse
import httpx

from app.config import settings
from app.schemas.scraper import ScraperRequest, ScraperResponse
from app.services.scraper import (
    BaseScraper,
    GoogleDriveScraper,
    GooglePhotosScraper,
    ICloudScraper,
    MyBoxScraper,
)
from app.core.exceptions import BadRequestException, ScraperException

logger = logging.getLogger(__name__)

router = APIRouter()


def get_scraper(provider: str) -> BaseScraper:
    scrapers = {
        "google_drive": GoogleDriveScraper,
        "google_photos": GooglePhotosScraper,
        "icloud": ICloudScraper,
        "mybox": MyBoxScraper,
    }
    scraper_class = scrapers.get(provider)
    if not scraper_class:
        raise BadRequestException(f"Unsupported provider: {provider}")
    return scraper_class()


@router.post("/scrape", response_model=ScraperResponse)
async def scrape_media(request: ScraperRequest):
    url = str(request.url)
    provider = BaseScraper.detect_provider(url)

    if not provider:
        raise BadRequestException(
            "Unable to detect provider. Supported: Google Drive, Google Photos, iCloud, Naver MyBox"
        )

    try:
        scraper = get_scraper(provider)
        media_items = await scraper.scrape(url)

        return ScraperResponse(
            success=True,
            url=url,
            provider=provider,
            media_count=len(media_items),
            media=media_items,
        )
    except Exception as e:
        raise ScraperException(f"Scraping failed: {str(e)}")


@router.post("/scrape/detect")
async def detect_provider(request: ScraperRequest):
    url = str(request.url)
    provider = BaseScraper.detect_provider(url)

    return {
        "url": url,
        "provider": provider,
        "supported": provider is not None,
    }


# ── 프록시 원본 호스트 allowlist + 호스트별 브라우저 캐시 정책 ──────────────
# 오픈 프록시 방지: 스크래퍼가 생성하는 미디어 도메인만 중계한다.
# (host, cache-control) — 서명 URL(icloud/mybox)은 URL 자체가 교체되므로
# 짧은 캐시도 무해하고, lh3/R2는 URL당 내용이 불변이라 길게 잡는다.
_R2_HOST = urlparse(settings.R2_PUBLIC_URL).netloc if settings.R2_PUBLIC_URL else None

_CACHE_IMMUTABLE = "public, max-age=31536000, immutable"
_CACHE_1DAY = "public, max-age=86400"
_CACHE_1HOUR = "public, max-age=3600"

_ALLOWED_HOSTS: dict[str, str] = {
    "lh3.googleusercontent.com": _CACHE_1DAY,
    "drive.google.com": _CACHE_1DAY,
    "photo.mybox.naver.com": _CACHE_1HOUR,
}
_ALLOWED_SUFFIXES: dict[str, str] = {
    ".icloud-content.com": _CACHE_1HOUR,
}


def _proxy_cache_policy(url: str) -> str | None:
    """허용 원본이면 Cache-Control 값을, 아니면 None을 반환."""
    host = urlparse(url).netloc.lower()
    if not host:
        return None
    if _R2_HOST and host == _R2_HOST.lower():
        return _CACHE_IMMUTABLE
    if host in _ALLOWED_HOSTS:
        return _ALLOWED_HOSTS[host]
    for suffix, policy in _ALLOWED_SUFFIXES.items():
        if host.endswith(suffix):
            return policy
    return None


# 원본 fetch 타임아웃: 죽은/만료 URL이 기본 30초 동안 매달리며 감상 화면
# 로딩을 붙잡던 문제 방지. read는 chunk 간 간격 기준이라 대용량 스트리밍에 안전.
_PROXY_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


@router.get("/proxy/image")
async def proxy_image(
    request: Request,
    url: str = Query(..., description="Media URL to proxy"),
):
    cache_control = _proxy_cache_policy(url)
    if cache_control is None:
        logger.warning("proxy_image: disallowed host for %s", url[:120])
        raise HTTPException(403, "Host not allowed")

    try:
        client: httpx.AsyncClient = request.app.state.http_client
        range_header = request.headers.get("range")
        req_headers = {"Range": range_header} if range_header else {}

        resp = await client.send(
            client.build_request(
                "GET", url, headers=req_headers, timeout=_PROXY_TIMEOUT
            ),
            stream=True,
        )

        async def generate():
            try:
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    yield chunk
            finally:
                await resp.aclose()

        res_headers = {
            "Content-Type": resp.headers.get("content-type", "application/octet-stream"),
            "Accept-Ranges": "bytes",
            "X-Accel-Buffering": "no",
        }
        # 성공 응답에만 브라우저 캐시 허용 (오류 응답이 캐시되면 안 됨)
        if resp.status_code in (200, 206):
            res_headers["Cache-Control"] = cache_control
        if "content-range" in resp.headers:
            res_headers["Content-Range"] = resp.headers["content-range"]
        if "content-length" in resp.headers:
            res_headers["Content-Length"] = resp.headers["content-length"]

        return StreamingResponse(
            generate(),
            status_code=resp.status_code,
            headers=res_headers,
        )
    except httpx.TimeoutException:
        logger.warning("Timeout fetching %s", url[:120])
        raise ScraperException("Media fetch timed out")
    except Exception as e:
        logger.exception("proxy_image error for %s", url[:120])
        raise ScraperException(f"Failed to fetch media: {str(e)}")
