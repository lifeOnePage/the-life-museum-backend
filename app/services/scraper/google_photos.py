import re
import logging
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

import httpx

from app.services.scraper.base import BaseScraper
from app.schemas.scraper import MediaItem, MediaType

logger = logging.getLogger(__name__)

# Regex: lh3 URLs with /pw/ path (album photos only, excludes /a/ profile pics)
_LH3_PHOTO_RE = re.compile(
    r'(https://lh3\.googleusercontent\.com/pw/[A-Za-z0-9_\-/]+(?:=[^\s"\'\\,\])}]+)?)'
)


def _ensure_desktop_redirect(url: str) -> str:
    """Append ?_imcp=1 to photos.app.goo.gl URLs to trigger server-side redirect
    to photos.google.com instead of the Firebase Dynamic Link page."""
    if "photos.app.goo.gl" in url:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if "_imcp" not in qs:
            qs["_imcp"] = ["1"]
            new_query = urlencode(qs, doseq=True)
            return urlunparse(parsed._replace(query=new_query))
    return url


class GooglePhotosScraper(BaseScraper):
    async def scrape(self, url: str) -> list[MediaItem]:
        fetch_url = _ensure_desktop_redirect(url)

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
            resp = await client.get(fetch_url)
            resp.raise_for_status()
            html = resp.text

        raw_urls = _LH3_PHOTO_RE.findall(html)
        logger.warning(
            "GooglePhotosScraper: status=%d html_length=%d lh3_count=%d url=%s final_url=%s",
            resp.status_code, len(html), len(raw_urls), url, resp.url,
        )

        media_items: list[MediaItem] = []
        seen_bases: set[str] = set()

        for src in raw_urls:
            item = self._process_google_url(src)
            if item and item.original_url not in seen_bases:
                seen_bases.add(item.original_url)
                media_items.append(item)

        return media_items

    def _process_google_url(self, src: str) -> MediaItem | None:
        if not src:
            return None

        # Strip any existing size params to get the base URL, then add high-res
        base = src.split("=")[0] if "=" in src else src
        original_url = base + "=w2000-h2000"
        thumbnail_url = base + "=w400-h400"

        # Detect if video (Google uses different patterns for video thumbnails)
        media_type = MediaType.VIDEO if "=m" in src else MediaType.IMAGE

        return MediaItem(
            type=media_type,
            thumbnail_url=thumbnail_url,
            original_url=original_url,
        )
