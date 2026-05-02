import logging
from fastapi import APIRouter, Query, Request
from fastapi.responses import Response
from starlette.responses import StreamingResponse
import httpx

from app.schemas.scraper import ScraperRequest, ScraperResponse
from app.services.scraper import BaseScraper, GooglePhotosScraper, ICloudScraper, MyBoxScraper
from app.core.exceptions import BadRequestException, ScraperException

logger = logging.getLogger(__name__)

router = APIRouter()


def get_scraper(provider: str) -> BaseScraper:
    scrapers = {
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
            "Unable to detect provider. Supported: Google Photos, iCloud, Naver MyBox"
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


@router.get("/proxy/image")
async def proxy_image(
    request: Request,
    url: str = Query(..., description="Media URL to proxy"),
):
    try:
        # First, resolve the final URL and get content info with a HEAD-like GET
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            # Check if browser sent a Range header
            range_header = request.headers.get("range")

            # For range requests (video seeking), fetch with Range pass-through
            if range_header:
                headers = {"Range": range_header}
                resp = await client.get(url, headers=headers)
                content_type = resp.headers.get("content-type", "application/octet-stream")
                resp_headers = {
                    "Accept-Ranges": "bytes",
                    "Content-Type": content_type,
                }
                if "content-range" in resp.headers:
                    resp_headers["Content-Range"] = resp.headers["content-range"]
                if "content-length" in resp.headers:
                    resp_headers["Content-Length"] = resp.headers["content-length"]
                return Response(
                    content=resp.content,
                    status_code=resp.status_code,  # 206 Partial Content
                    headers=resp_headers,
                )

            # Non-range request: fetch full content
            resp = await client.get(url)

            if resp.status_code != 200:
                logger.warning("Upstream %s for %s", resp.status_code, url[:120])
                return Response(status_code=resp.status_code, content=b"Upstream error")

            content_type = resp.headers.get("content-type", "image/jpeg")
            resp_headers = {"Accept-Ranges": "bytes"}
            return Response(
                content=resp.content,
                media_type=content_type,
                headers=resp_headers,
            )
    except httpx.TimeoutException:
        logger.warning("Timeout fetching %s", url[:120])
        raise ScraperException("Media fetch timed out")
    except Exception as e:
        logger.exception("proxy_image error for %s", url[:120])
        raise ScraperException(f"Failed to fetch media: {str(e)}")
