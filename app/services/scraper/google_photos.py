import re
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor

from selenium.webdriver.common.by import By

from app.services.scraper.base import BaseScraper
from app.schemas.scraper import MediaItem, MediaType


class GooglePhotosScraper(BaseScraper):
    # 최소 이미지 크기 (픽셀) - 이보다 작은 이미지는 프로필 사진 등으로 간주하고 제외
    MIN_IMAGE_SIZE = 100

    async def scrape(self, url: str) -> list[MediaItem]:
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as executor:
            return await loop.run_in_executor(executor, self._scrape_sync, url)

    def _scrape_sync(self, url: str) -> list[MediaItem]:
        self._init_driver()
        try:
            self.driver.get(url)
            time.sleep(3)

            # Scroll to load all images
            self._scroll_page()

            media_items = []
            seen_originals = set()

            # Collect from img tags
            img_elements = self.driver.find_elements(By.TAG_NAME, "img")
            for img in img_elements:
                src = img.get_attribute("src") or ""
                if "googleusercontent.com" in src:
                    # 이미지 크기 확인
                    width = img.size.get("width", 0)
                    height = img.size.get("height", 0)

                    # 최소 크기 미만이면 스킵 (프로필 사진 등 제외)
                    if width < self.MIN_IMAGE_SIZE or height < self.MIN_IMAGE_SIZE:
                        continue

                    item = self._process_google_url(src)
                    if item and item.original_url not in seen_originals:
                        seen_originals.add(item.original_url)
                        media_items.append(item)

            # Collect from background images
            bg_elements = self.driver.find_elements(By.XPATH, "//*[@style]")
            for el in bg_elements:
                style = el.get_attribute("style") or ""
                if "googleusercontent.com" in style and "background-image" in style:
                    # 요소 크기 확인
                    width = el.size.get("width", 0)
                    height = el.size.get("height", 0)

                    if width < self.MIN_IMAGE_SIZE or height < self.MIN_IMAGE_SIZE:
                        continue

                    urls = re.findall(r'url\(["\']?(.*?)["\']?\)', style)
                    for src in urls:
                        if "googleusercontent.com" in src:
                            item = self._process_google_url(src)
                            if item and item.original_url not in seen_originals:
                                seen_originals.add(item.original_url)
                                media_items.append(item)

            return media_items
        finally:
            self._quit_driver()

    def _scroll_page(self, max_scrolls: int = 5):
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        for _ in range(max_scrolls):
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

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
