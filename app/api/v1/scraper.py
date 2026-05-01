import logging
from fastapi import APIRouter, Query
from fastapi.responses import Response
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
async def proxy_image(url: str = Query(..., description="Media URL to proxy")):
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            resp = await client.get(url)

            if resp.status_code != 200:
                logger.warning("Upstream %s for %s", resp.status_code, url[:120])
                return Response(status_code=resp.status_code, content=b"Upstream error")

            content_type = resp.headers.get("content-type", "image/jpeg")
            return Response(content=resp.content, media_type=content_type)
    except httpx.TimeoutException:
        logger.warning("Timeout fetching %s", url[:120])
        raise ScraperException("Media fetch timed out")
    except Exception as e:
        logger.exception("proxy_image error for %s", url[:120])
        raise ScraperException(f"Failed to fetch media: {str(e)}")
