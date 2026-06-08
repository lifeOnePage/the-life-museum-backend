import re
import time
import uuid
import base64
import asyncio
from concurrent.futures import ThreadPoolExecutor

import boto3
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from app.config import settings
from app.services.scraper.base import BaseScraper
from app.schemas.scraper import MediaItem, MediaType


class ICloudScraper(BaseScraper):
    def __init__(self, headless: bool = True):
        super().__init__(headless=headless)
        self._s3 = None

    def _get_s3_client(self):
        if self._s3 is None:
            self._s3 = boto3.client(
                "s3",
                endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
                aws_access_key_id=settings.R2_ACCESS_KEY_ID,
                aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
                region_name="auto",
            )
        return self._s3

    def _upload_blob_to_r2(self, blob_url: str) -> str | None:
        data_url = self._convert_blob_to_data_url(blob_url)
        if not data_url:
            return None
        match = re.match(r'data:image/(\w+);base64,(.+)', data_url)
        if not match:
            return None
        ext = match.group(1).replace('jpeg', 'jpg')
        image_bytes = base64.b64decode(match.group(2))
        key = f"icloud/{uuid.uuid4()}.{ext}"
        self._get_s3_client().put_object(
            Bucket=settings.R2_BUCKET_NAME,
            Key=key,
            Body=image_bytes,
            ContentType=f"image/{match.group(1)}",
        )
        return f"{settings.R2_PUBLIC_URL}/{key}"

    async def scrape(self, url: str, progress_callback=None) -> list[MediaItem]:
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as executor:
            return await loop.run_in_executor(
                executor, self._scrape_sync, url, progress_callback
            )

    def _scrape_sync(self, url: str, progress_callback=None) -> list[MediaItem]:
        self._init_driver()
        try:
            if progress_callback:
                progress_callback({"step": "page_loading"})
            self.driver.get(url)
            time.sleep(8)

            if progress_callback:
                progress_callback({"step": "waiting_for_content"})
            # Wait for the first photo group to render
            try:
                WebDriverWait(self.driver, 20).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, ".x-stream-photo-group-view")
                    )
                )
            except Exception:
                pass

            # Scroll each group into view and collect images immediately
            # (iCloud virtualizes DOM — images are removed when scrolled away)
            media_items = []
            seen = set()
            self._scroll_and_collect(media_items, seen, progress_callback)

            if progress_callback:
                progress_callback({"step": "collecting_media", "found": len(media_items)})

            return media_items
        finally:
            self._quit_driver()

    def _resolve_image_url(self, src: str) -> str | None:
        """Convert blob URL to R2 URL, or return CDN URL as-is."""
        if src.startswith("blob:"):
            return self._upload_blob_to_r2(src)
        return src

    def _collect_visible_images(self, container, media_items: list, seen: set):
        """Collect iCloud content images from a visible DOM container."""
        imgs = container.find_elements(By.TAG_NAME, "img")
        for img in imgs:
            src = img.get_attribute("src") or ""
            if not src:
                continue
            if ("icloud-content.com" in src or src.startswith("blob:")) and src not in seen:
                seen.add(src)
                url = self._resolve_image_url(src)
                if url:
                    media_items.append(
                        MediaItem(type=MediaType.IMAGE, thumbnail_url=url, original_url=url)
                    )

    def _scroll_and_collect(self, media_items: list, seen: set, progress_callback=None):
        """Two-phase scroll: activate each group, then collect from each item.

        iCloud virtualizes the DOM at two levels:
        1. Group blocks with class 'not-visible' have no child grid items
        2. Grid items only render <img> tags when scrolled into view
        """
        groups = self.driver.find_elements(
            By.CSS_SELECTOR, ".x-stream-photo-group-block-view"
        )
        # Process in reverse order (bottom→top) so large grid groups
        # are handled first, before iCloud's image view recycling
        # interferes with smaller groups loaded earlier.
        for gi in reversed(range(len(groups))):
            group = groups[gi]
            # Activate group
            self.driver.execute_script(
                "arguments[0].scrollIntoView({behavior:'instant',block:'start'});",
                group,
            )
            time.sleep(3)
            for _ in range(10):
                if "not-visible" not in (group.get_attribute("class") or ""):
                    break
                time.sleep(0.5)

            # Scroll each grid item into center and collect
            items = group.find_elements(
                By.CSS_SELECTOR, ".x-stream-photo-grid-item-view"
            )
            for item in items:
                self.driver.execute_script(
                    "arguments[0].scrollIntoView({behavior:'instant',block:'center'});",
                    item,
                )
                for _ in range(8):
                    if item.find_elements(By.TAG_NAME, "img"):
                        break
                    time.sleep(0.5)
                self._collect_visible_images(item, media_items, seen)

            if progress_callback:
                progress_callback({
                    "step": "scrolling",
                    "current": len(groups) - gi,
                    "total": len(groups),
                })

    def _convert_blob_to_data_url(self, blob_url: str) -> str | None:
        script = """
        async function blobToBase64(blobUrl) {
            try {
                const response = await fetch(blobUrl);
                const blob = await response.blob();
                return new Promise((resolve, reject) => {
                    const reader = new FileReader();
                    reader.onloadend = () => resolve(reader.result);
                    reader.onerror = reject;
                    reader.readAsDataURL(blob);
                });
            } catch (e) {
                return null;
            }
        }
        return await blobToBase64(arguments[0]);
        """
        try:
            return self.driver.execute_script(script, blob_url)
        except Exception:
            return None
