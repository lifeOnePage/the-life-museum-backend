from fastapi import APIRouter, Query
from fastapi.responses import Response
from starlette.responses import StreamingResponse
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
async def proxy_image(url: str = Query(..., description="Media URL to proxy")):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://photos.google.com/",
    }
    try:
        async with httpx.AsyncClient(follow_redirects=True, headers=headers) as client:
            req = client.build_request("GET", url)
            resp = await client.send(req, stream=True, timeout=30.0)

            if resp.status_code != 200:
                await resp.aclose()
                return Response(status_code=resp.status_code, content=b"Upstream error")

            content_type = resp.headers.get("content-type", "image/jpeg")

            if content_type.startswith("video/"):
                # Video: stream chunks (client closes when generator ends)
                content = await resp.aread()
                return Response(content=content, media_type=content_type)

            # Images: read fully (small, benefits from Content-Length)
            content = await resp.aread()
            return Response(content=content, media_type=content_type)
    except httpx.TimeoutException:
        raise ScraperException("Media fetch timed out")
    except Exception as e:
        raise ScraperException(f"Failed to fetch media: {str(e)}")
