import re
import asyncio
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
    _PROBE_CONCURRENCY = 10
    _PROBE_TIMEOUT = 5.0

    async def _probe_media_type(
        self,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        base_url: str,
    ) -> tuple[str, MediaType]:
        """HEAD probe base_url=dv -> video면 VIDEO, 아니면 IMAGE."""
        async with semaphore:
            try:
                resp = await client.head(
                    base_url + "=dv",
                    follow_redirects=True,
                    timeout=self._PROBE_TIMEOUT,
                )
                ct = resp.headers.get("content-type", "")
                if resp.status_code == 200 and ct.startswith("video/"):
                    return (base_url, MediaType.VIDEO)
            except (httpx.TimeoutException, httpx.HTTPError):
                pass
        return (base_url, MediaType.IMAGE)

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
            # Phase 1: HTML fetch + URL extraction
            resp = await client.get(fetch_url)
            resp.raise_for_status()
            html = resp.text
            raw_urls = _LH3_PHOTO_RE.findall(html)

            # Phase 2: deduplicate by base URL
            seen_bases: dict[str, str] = {}  # base -> original src
            for src in raw_urls:
                base = src.split("=")[0] if "=" in src else src
                if base not in seen_bases:
                    seen_bases[base] = src

            if not seen_bases:
                return []

            # Phase 3: concurrent HEAD probing
            semaphore = asyncio.Semaphore(self._PROBE_CONCURRENCY)
            tasks = [
                self._probe_media_type(client, semaphore, b) for b in seen_bases
            ]
            results = await asyncio.gather(*tasks)
            type_map = dict(results)

        # Phase 4: build MediaItem list
        media_items: list[MediaItem] = []
        for base, src in seen_bases.items():
            media_type = type_map.get(base, MediaType.IMAGE)
            # Fallback: if HEAD failed but HTML contains =m, treat as video
            if media_type == MediaType.IMAGE and "=m" in src:
                media_type = MediaType.VIDEO

            thumbnail_url = base + "=w400-h400"
            original_url = (
                (base + "=dv") if media_type == MediaType.VIDEO else (base + "=w2000-h2000")
            )
            media_items.append(
                MediaItem(
                    type=media_type,
                    thumbnail_url=thumbnail_url,
                    original_url=original_url,
                )
            )

        logger.info(
            "GooglePhotosScraper: %d URLs, %d videos detected",
            len(media_items),
            sum(1 for m in media_items if m.type == MediaType.VIDEO),
        )
        return media_items
