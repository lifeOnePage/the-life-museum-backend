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
        # iCloud often requires non-headless for proper loading
        super().__init__(headless=False)
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
            time.sleep(5)

            if progress_callback:
                progress_callback({"step": "waiting_for_content"})
            # Wait for images to load
            try:
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "img"))
                )
            except Exception:
                pass

            # Scroll to load all content
            self._scroll_page(progress_callback=progress_callback)

            media_items = []
            seen = set()

            # Collect from img tags
            img_elements = self.driver.find_elements(By.TAG_NAME, "img")
            for img in img_elements:
                src = img.get_attribute("src") or ""
                if not src:
                    continue

                if "icloud-content.com" in src or src.startswith("blob:"):
                    if src not in seen:
                        seen.add(src)
                        if src.startswith("blob:"):
                            r2_url = self._upload_blob_to_r2(src)
                            if r2_url:
                                media_items.append(
                                    MediaItem(
                                        type=MediaType.IMAGE,
                                        thumbnail_url=r2_url,
                                        original_url=r2_url,
                                    )
                                )
                        else:
                            media_items.append(
                                MediaItem(
                                    type=MediaType.IMAGE,
                                    thumbnail_url=src,
                                    original_url=src,
                                )
                            )

            # Collect from background images
            bg_elements = self.driver.find_elements(By.XPATH, "//*[@style]")
            for el in bg_elements:
                style = el.get_attribute("style") or ""
                if "background-image" not in style:
                    continue
                urls = re.findall(
                    r'url\(["\']?(blob:[^"\')\s]+|https?://[^"\')\s]+)["\']?\)',
                    style,
                )
                for u in urls:
                    if ("icloud-content.com" in u or u.startswith("blob:")) and u not in seen:
                        seen.add(u)
                        if u.startswith("blob:"):
                            r2_url = self._upload_blob_to_r2(u)
                            if r2_url:
                                media_items.append(
                                    MediaItem(
                                        type=MediaType.IMAGE,
                                        thumbnail_url=r2_url,
                                        original_url=r2_url,
                                    )
                                )
                        else:
                            media_items.append(
                                MediaItem(
                                    type=MediaType.IMAGE,
                                    thumbnail_url=u,
                                    original_url=u,
                                )
                            )

            if progress_callback:
                progress_callback({"step": "collecting_media", "found": len(media_items)})

            return media_items
        finally:
            self._quit_driver()

    def _scroll_page(self, max_scrolls: int = 20, progress_callback=None):
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        for i in range(max_scrolls):
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5)
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            if progress_callback:
                progress_callback({"step": "scrolling", "current": i + 1, "total": max_scrolls})
            if new_height == last_height:
                break
            last_height = new_height

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
