import logging
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class AlbumMetadata:
    title: str
    cover_photo_url: str | None


class GooglePhotosAPI:
    BASE_URL = "https://photoslibrary.googleapis.com/v1"
    TOKEN_URL = "https://oauth2.googleapis.com/token"

    async def get_album_metadata(
        self,
        share_url: str,
        access_token: str,
        refresh_token: str | None,
    ) -> AlbumMetadata | None:
        """공유 앨범 URL로 앨범 메타데이터 조회."""
        resolved_url = await self._resolve_share_url(share_url)

        try:
            albums = await self._list_shared_albums(access_token)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401 and refresh_token:
                logger.info("Access token expired, refreshing...")
                access_token = await self._refresh_access_token(refresh_token)
                albums = await self._list_shared_albums(access_token)
            else:
                raise

        for album in albums:
            share_info = album.get("shareInfo", {})
            shareable_url = share_info.get("shareableUrl", "")
            if self._urls_match(shareable_url, resolved_url):
                title = album.get("title", "")
                cover_base_url = album.get("coverPhotoBaseUrl")
                cover_url = f"{cover_base_url}=w2000-h2000" if cover_base_url else None
                return AlbumMetadata(title=title, cover_photo_url=cover_url)

        logger.warning("No matching album found for URL: %s", share_url)
        return None

    async def _list_shared_albums(self, access_token: str) -> list[dict]:
        """페이지네이션하여 모든 공유 앨범 조회."""
        albums: list[dict] = []
        next_page_token = None

        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                params = {"pageSize": 50}
                if next_page_token:
                    params["pageToken"] = next_page_token

                resp = await client.get(
                    f"{self.BASE_URL}/sharedAlbums",
                    params=params,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                resp.raise_for_status()
                data = resp.json()

                albums.extend(data.get("sharedAlbums", []))
                next_page_token = data.get("nextPageToken")
                if not next_page_token:
                    break

        return albums

    async def _refresh_access_token(self, refresh_token: str) -> str:
        """만료된 access token 갱신."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                self.TOKEN_URL,
                data={
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            resp.raise_for_status()
            return resp.json()["access_token"]

    async def _resolve_share_url(self, url: str) -> str:
        """photos.app.goo.gl 단축 URL → photos.google.com 전체 URL로 변환."""
        parsed = urlparse(url)
        if parsed.hostname in ("photos.app.goo.gl", "goo.gl"):
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.head(url)
                return str(resp.url)
        return url

    @staticmethod
    def _urls_match(url_a: str, url_b: str) -> bool:
        """두 URL이 같은 앨범을 가리키는지 비교 (쿼리스트링 무시)."""
        parsed_a = urlparse(url_a)
        parsed_b = urlparse(url_b)
        # 호스트 + 경로만 비교 (끝 슬래시 정규화)
        return (
            parsed_a.hostname == parsed_b.hostname
            and parsed_a.path.rstrip("/") == parsed_b.path.rstrip("/")
        )
