import re
import logging

import httpx

from app.services.scraper.base import BaseScraper
from app.schemas.scraper import MediaItem, MediaType

logger = logging.getLogger(__name__)

# Regex to find lh3.googleusercontent.com URLs in the HTML/JS source
_LH3_URL_RE = re.compile(
    r'(https://lh3\.googleusercontent\.com/[A-Za-z0-9_\-/]+(?:=[^\s"\'\\,\])}]+)?)'
)


class GooglePhotosScraper(BaseScraper):
    async def scrape(self, url: str) -> list[MediaItem]:
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
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text

        raw_urls = _LH3_URL_RE.findall(html)
        logger.warning(
            "GooglePhotosScraper: status=%d html_length=%d lh3_count=%d url=%s",
            resp.status_code, len(html), len(raw_urls), url,
        )

        media_items: list[MediaItem] = []
        seen_originals: set[str] = set()

        for src in raw_urls:
            item = self._process_google_url(src)
            if item and item.original_url not in seen_originals:
                seen_originals.add(item.original_url)
                media_items.append(item)

        logger.info("Returning %d unique media items", len(media_items))
        return media_items

    def _process_google_url(self, src: str) -> MediaItem | None:
        if not src:
            return None

        # Convert to high resolution
        if "=w" in src:
            original_url = src.split("=w")[0] + "=w2000-h2000"
        else:
            original_url = src

        # Detect if video (Google uses different patterns for video thumbnails)
        media_type = MediaType.VIDEO if "=m" in src else MediaType.IMAGE

        return MediaItem(
            type=media_type,
            thumbnail_url=src,
            original_url=original_url,
        )
