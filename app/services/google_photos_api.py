import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


@dataclass
class AlbumMetadata:
    title: str
    subtitle: str | None
    cover_photo_url: str | None
    cover_photo_bytes: bytes | None = None
    cover_photo_content_type: str | None = None


class GooglePhotosAPI:
    """Google Photos 공유 앨범 URL에서 OG 메타태그로 메타데이터 추출."""

    async def get_album_metadata(self, share_url: str) -> AlbumMetadata | None:
        """공유 앨범 URL의 OG 메타태그에서 제목/커버 이미지 추출."""
        resolved_url = await self._resolve_share_url(share_url)

        try:
            async with httpx.AsyncClient(
                timeout=15,
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                },
            ) as client:
                resp = await client.get(resolved_url)
                resp.raise_for_status()
                html = resp.text
        except Exception as e:
            logger.warning("Failed to fetch Google Photos URL %s: %s", share_url, e)
            return None

        title = self._extract_og_tag(html, "og:title")
        cover_url = self._extract_og_tag(html, "og:image")

        if not title and not cover_url:
            logger.warning("No OG meta tags found for URL: %s", share_url)
            return None

        logger.info(
            "OG metadata for %s — title=%r, cover=%s",
            share_url,
            title,
            cover_url[:80] if cover_url else None,
        )

        # "ㅇㅇ · Jan 19 – 23, 2024 📸" → title="ㅇㅇ", subtitle="Jan 19 – 23, 2024"
        parsed_title, parsed_subtitle = self._parse_og_title(title or "")

        # Download cover image bytes for R2 re-upload (avoids CORS issues)
        cover_bytes = None
        cover_content_type = None
        if cover_url:
            cover_bytes, cover_content_type = await self._download_image(cover_url)

        return AlbumMetadata(
            title=parsed_title,
            subtitle=parsed_subtitle,
            cover_photo_url=cover_url,
            cover_photo_bytes=cover_bytes,
            cover_photo_content_type=cover_content_type,
        )

    @staticmethod
    def _strip_emoji(text: str) -> str:
        """이모지 제거."""
        return re.sub(
            r'[\U0001F300-\U0001FAFF\U00002702-\U000027B0\U0000FE00-\U0000FE0F\U0000200D]+',
            '', text,
        ).strip()

    @classmethod
    def _parse_og_title(cls, raw_title: str) -> tuple[str, str | None]:
        """OG 제목을 title · subtitle 로 분리. 이모지 제거.

        예: "ㅇㅇ · Jan 19 – 23, 2024 📸" → ("ㅇㅇ", "Jan 19 – 23, 2024")
        """
        if not raw_title:
            return "", None

        # middot(·) 또는 bullet(•) 구분자 기준 분리
        parts = re.split(r'\s*[·•]\s*', raw_title, maxsplit=1)
        title = cls._strip_emoji(parts[0])
        subtitle = cls._strip_emoji(parts[1]) if len(parts) > 1 else None

        return title, subtitle or None

    @staticmethod
    def _extract_og_tag(html: str, property_name: str) -> str | None:
        """HTML에서 <meta property="og:xxx" content="..."> 값 추출."""
        pattern = (
            rf'<meta\s+[^>]*property=["\']({re.escape(property_name)})["\']'
            rf'\s+[^>]*content=["\']([^"\']*)["\']'
        )
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            return match.group(2).strip()

        # content가 property 앞에 오는 경우
        pattern_rev = (
            rf'<meta\s+[^>]*content=["\']([^"\']*)["\']'
            rf'\s+[^>]*property=["\']({re.escape(property_name)})["\']'
        )
        match_rev = re.search(pattern_rev, html, re.IGNORECASE)
        if match_rev:
            return match_rev.group(1).strip()

        return None

    async def _download_image(self, url: str) -> tuple[bytes | None, str | None]:
        """이미지 URL에서 바이트 다운로드. 실패 시 (None, None)."""
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0]
                return resp.content, content_type
        except Exception as e:
            logger.warning("Failed to download cover image %s: %s", url[:80], e)
            return None, None

    async def _resolve_share_url(self, url: str) -> str:
        """photos.app.goo.gl 단축 URL → photos.google.com 전체 URL로 변환."""
        parsed = urlparse(url)
        if parsed.hostname in ("photos.app.goo.gl", "goo.gl"):
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.head(url)
                return str(resp.url)
        return url
