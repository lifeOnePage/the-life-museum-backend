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
    try:
        client = httpx.AsyncClient(follow_redirects=True)
        req = client.build_request("GET", url)
        resp = await client.send(req, stream=True, timeout=300.0)

        content_type = resp.headers.get("content-type", "image/jpeg")

        if content_type.startswith("video/"):
            async def stream_video():
                try:
                    async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                        yield chunk
                finally:
                    await resp.aclose()
                    await client.aclose()

            return StreamingResponse(stream_video(), media_type=content_type)

        # Images: read fully (small, benefits from Content-Length)
        content = await resp.aread()
        await resp.aclose()
        await client.aclose()
        return Response(content=content, media_type=content_type)
    except Exception as e:
        raise ScraperException(f"Failed to fetch media: {str(e)}")
