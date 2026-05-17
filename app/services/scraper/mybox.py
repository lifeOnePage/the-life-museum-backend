import re
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from app.services.scraper.base import BaseScraper
from app.schemas.scraper import MediaItem, MediaType


class MyBoxScraper(BaseScraper):
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

            img_elements = self.driver.find_elements(By.TAG_NAME, "img")
            for img in img_elements:
                src = img.get_attribute("src") or ""
                if not src or not src.startswith("http"):
                    continue

                # Only MyBox photo URLs
                if "photo.mybox.naver.com" not in src:
                    continue

                # Convert to original size
                original = re.sub(r"type=[^&]*", "type=original", src)

                if original not in seen:
                    seen.add(original)
                    media_items.append(
                        MediaItem(
                            type=MediaType.IMAGE,
                            thumbnail_url=src,
                            original_url=original,
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
