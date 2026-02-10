from fastapi import APIRouter, Query
from fastapi.responses import Response
import httpx

from app.schemas.scraper import ScraperRequest, ScraperResponse
from app.services.scraper import BaseScraper, GooglePhotosScraper, ICloudScraper, MyBoxScraper
from app.core.exceptions import BadRequestException, ScraperException

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
async def proxy_image(url: str = Query(..., description="Image URL to proxy")):
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=300.0)
            return Response(
                content=resp.content,
                media_type=resp.headers.get("content-type", "image/jpeg"),
            )
    except Exception as e:
        raise ScraperException(f"Failed to fetch image: {str(e)}")
