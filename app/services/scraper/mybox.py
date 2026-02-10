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
