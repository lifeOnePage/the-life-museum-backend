import logging
import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from typing import Callable

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

from app.schemas.scraper import MediaItem

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict], None] | None


class BaseScraper(ABC):
    @staticmethod
    def _find_chromedriver() -> str | None:
        """Find chromedriver: env var > PATH > subprocess which > local fallback."""
        # 0. Explicit env var (set by nixpacks start command)
        env_path = os.environ.get("CHROMEDRIVER_PATH")
        if env_path and os.path.isfile(env_path):
            logger.info("chromedriver found via CHROMEDRIVER_PATH: %s", env_path)
            return env_path

        # 1. System PATH
        system = shutil.which("chromedriver")
        if system:
            logger.info("chromedriver found via shutil.which: %s", system)
            return system

        # 2. subprocess which (catches cases shutil.which misses in nix)
        try:
            result = subprocess.run(
                ["which", "chromedriver"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                path = result.stdout.strip()
                if os.path.isfile(path):
                    logger.info("chromedriver found via subprocess which: %s", path)
                    return path
        except Exception:
            pass

        # 3. Common nix profile paths (Railway/nixpacks)
        for nix_path in [
            "/nix/var/nix/profiles/default/bin/chromedriver",
            "/root/.nix-profile/bin/chromedriver",
            "/run/current-system/sw/bin/chromedriver",
        ]:
            if os.path.isfile(nix_path):
                logger.info("chromedriver found via nix path: %s", nix_path)
                return nix_path

        # 4. Search nix store (last resort before Selenium Manager)
        try:
            result = subprocess.run(
                ["find", "/nix/store", "-name", "chromedriver", "-type", "f",
                 "-path", "*/bin/chromedriver"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                path = result.stdout.strip().split("\n")[0]
                if os.path.isfile(path):
                    logger.info("chromedriver found via nix store search: %s", path)
                    return path
        except Exception:
            pass

        # 5. Local macOS fallback (webdriver-manager cache)
        local = os.path.expanduser(
            "~/.wdm/drivers/chromedriver/mac64/148.0.7778.178/chromedriver-mac-arm64/chromedriver"
        )
        if os.path.isfile(local):
            logger.info("chromedriver found via local fallback: %s", local)
            return local

        logger.warning("chromedriver not found by any method")
        return None

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
        options.add_argument("--disable-software-rasterizer")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        # Chromium binary: env var first, then PATH lookup, then nix paths
        chromium_bin = (
            os.environ.get("CHROMIUM_BIN")
            or shutil.which("chromium")
            or shutil.which("chromium-browser")
            or shutil.which("google-chrome")
        )
        if not chromium_bin:
            for nix_path in [
                "/nix/var/nix/profiles/default/bin/chromium",
                "/root/.nix-profile/bin/chromium",
            ]:
                if os.path.isfile(nix_path):
                    chromium_bin = nix_path
                    break
        if chromium_bin and os.path.isfile(chromium_bin):
            options.binary_location = chromium_bin
            logger.info("Chromium binary: %s", chromium_bin)
        return options

    def _init_driver(self):
        chromedriver_path = self._find_chromedriver()
        if chromedriver_path:
            service = Service(chromedriver_path)
        else:
            logger.warning("No chromedriver path found, using Service() default (Selenium Manager)")
            service = Service()
        self.driver = webdriver.Chrome(service=service, options=self._get_chrome_options())
        logger.info("Chrome driver initialized successfully")

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
        if "drive.google.com" in url_lower:
            return "google_drive"
        elif "photos.google.com" in url_lower or "photos.app.goo.gl" in url_lower:
            return "google_photos"
        elif "icloud.com" in url_lower:
            return "icloud"
        elif "mybox.naver.com" in url_lower or "naver.me" in url_lower:
            return "mybox"
        return None
