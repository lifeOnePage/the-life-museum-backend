import logging
from fastapi import APIRouter, Query, Request
from starlette.responses import StreamingResponse
import httpx

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


@router.get("/proxy/image")
async def proxy_image(
    request: Request,
    url: str = Query(..., description="Media URL to proxy"),
):
    try:
        client: httpx.AsyncClient = request.app.state.http_client
        range_header = request.headers.get("range")
        req_headers = {"Range": range_header} if range_header else {}

        resp = await client.send(
            client.build_request("GET", url, headers=req_headers),
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
