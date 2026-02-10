import re
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from app.services.scraper.base import BaseScraper
from app.schemas.scraper import MediaItem, MediaType


class ICloudScraper(BaseScraper):
    def __init__(self, headless: bool = True):
        # iCloud often requires non-headless for proper loading
        super().__init__(headless=False)

    async def scrape(self, url: str) -> list[MediaItem]:
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as executor:
            return await loop.run_in_executor(executor, self._scrape_sync, url)

    def _scrape_sync(self, url: str) -> list[MediaItem]:
        self._init_driver()
        try:
            self.driver.get(url)
            time.sleep(5)

            # Wait for images to load
            try:
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "img"))
                )
            except Exception:
                pass

            # Scroll to load all content
            self._scroll_page()

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
                        # For blob URLs, we need to convert them
                        if src.startswith("blob:"):
                            original_url = self._convert_blob_to_data_url(src)
                            if original_url:
                                media_items.append(
                                    MediaItem(
                                        type=MediaType.IMAGE,
                                        thumbnail_url=src,
                                        original_url=original_url,
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
                            original_url = self._convert_blob_to_data_url(u)
                            if original_url:
                                media_items.append(
                                    MediaItem(
                                        type=MediaType.IMAGE,
                                        thumbnail_url=u,
                                        original_url=original_url,
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

            return media_items
        finally:
            self._quit_driver()

    def _scroll_page(self, max_scrolls: int = 20):
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        for _ in range(max_scrolls):
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5)
            new_height = self.driver.execute_script("return document.body.scrollHeight")
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
