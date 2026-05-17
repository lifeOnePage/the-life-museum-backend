import os
from abc import ABC, abstractmethod
from typing import Callable

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

from app.schemas.scraper import MediaItem

ProgressCallback = Callable[[dict], None] | None


class BaseScraper(ABC):
    # 직접 chromedriver 경로 지정
    CHROMEDRIVER_PATH = os.path.expanduser(
        "~/.wdm/drivers/chromedriver/mac64/144.0.7559.133/chromedriver-mac-arm64/chromedriver"
    )

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.driver = None

    def _get_chrome_options(self) -> Options:
        options = Options()
        if self.headless:
            options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        return options

    def _init_driver(self):
        service = Service(self.CHROMEDRIVER_PATH)
        self.driver = webdriver.Chrome(service=service, options=self._get_chrome_options())

    def _quit_driver(self):
        if self.driver:
            self.driver.quit()
            self.driver = None

    @abstractmethod
    async def scrape(self, url: str, progress_callback: ProgressCallback = None) -> list[MediaItem]:
        pass

    @staticmethod
    def detect_provider(url: str) -> str | None:
        url_lower = url.lower()
        if "photos.google.com" in url_lower or "photos.app.goo.gl" in url_lower:
            return "google_photos"
        elif "icloud.com" in url_lower:
            return "icloud"
        elif "mybox.naver.com" in url_lower or "naver.me" in url_lower:
            return "mybox"
        return None
