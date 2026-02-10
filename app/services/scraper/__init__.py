from app.services.scraper.base import BaseScraper
from app.services.scraper.google_photos import GooglePhotosScraper
from app.services.scraper.icloud import ICloudScraper
from app.services.scraper.mybox import MyBoxScraper

__all__ = ["BaseScraper", "GooglePhotosScraper", "ICloudScraper", "MyBoxScraper"]
