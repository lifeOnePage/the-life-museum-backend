import re
import time
import uuid
import base64
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

import boto3
import httpx
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from app.config import settings
from app.services.scraper.base import BaseScraper
from app.schemas.scraper import MediaItem, MediaType

logger = logging.getLogger(__name__)

# ── CloudKit 공개 공유 API ────────────────────────────────────────────────────
# 신형 공유 링크(share.icloud.com/photos/<token>)는 사진 앱(photos3/CMM)이
# 렌더링하며, 구형 공유앨범(icloud.com/sharedalbum/#B...)과 DOM 구조가 완전히
# 다르다(iframe + 다른 클래스명). 그래서 구형 셀렉터 기반 Selenium 스크랩은
# 신형 링크에서 항상 0건을 반환했다.
#
# 신형 링크는 브라우저 없이 CloudKit 공개 API 2회 호출로 전체 목록을 얻는다:
#   1) public/records/resolve  — shortGUID → zoneID + 익명 접근 토큰
#   2) shared/records/query    — 존의 에셋 목록(페이지네이션)
# 반환되는 downloadURL은 서명 URL(수명 짧음)이라 media_cache의 icloud TTL(300s)
# 및 프록시 1시간 캐시 정책과 정합한다.
_CK_BASE = "https://ckdatabasews.icloud.com/database/1/com.apple.photos.cloud/production"
_CK_HEADERS = {
    "Content-Type": "text/plain",
    "Origin": "https://www.icloud.com",
    "Referer": "https://www.icloud.com/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}
# 공유 링크 토큰: /photos/<token> 또는 #<token>
_SHARE_TOKEN_RE = re.compile(r"share\.icloud\.com/photos/([A-Za-z0-9_-]+)")

# CloudKit 스마트 인덱스 — 숨김/삭제 제외한 에셋을 날짜순으로 조회
_QUERY_RECORD_TYPE = "CPLAssetAndMasterByAssetDateWithoutHiddenOrDeleted"
_PAGE_SIZE = 200
_MAX_PAGES = 60  # 안전 상한 (최대 12,000장)

# itemType(UTI) → MediaType. 접두어로 판별되지 않는 것은 이미지로 취급.
_VIDEO_UTI_HINTS = ("movie", "mpeg-4", "video", "quicktime")


def _is_video(item_type: str) -> bool:
    t = (item_type or "").lower()
    return any(h in t for h in _VIDEO_UTI_HINTS)


def _decode_b64_field(fields: dict, key: str) -> str:
    """CloudKit의 base64 인코딩 문자열 필드(filenameEnc 등)를 디코드."""
    raw = fields.get(key, {}).get("value")
    if not raw:
        return ""
    try:
        return base64.b64decode(raw).decode("utf-8", "replace")
    except Exception:
        return ""


def _asset_url(fields: dict, key: str, filename: str) -> str | None:
    """리소스 필드에서 다운로드 URL 추출. `${f}` 자리표시자를 파일명으로 치환."""
    res = fields.get(key, {}).get("value")
    if not isinstance(res, dict):
        return None
    url = res.get("downloadURL")
    if not url or "${f}" not in url and not url.startswith("http"):
        return None
    # 파일명이 없으면 자리표시자만 제거(서버는 임의 세그먼트를 허용)
    return url.replace("${f}", filename or "f")


class ICloudScraper(BaseScraper):
    def __init__(self, headless: bool = True):
        super().__init__(headless=headless)
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
            # uuid 파일명 → 내용 불변. 브라우저/CDN 1년 캐시
            CacheControl="public, max-age=31536000, immutable",
        )
        return f"{settings.R2_PUBLIC_URL}/{key}"

    async def scrape(self, url: str, progress_callback=None, images_only: bool = False) -> list[MediaItem]:
        # 신형 공유 링크는 브라우저 없이 CloudKit API로 처리 (빠르고 전량 수집)
        token = self._extract_share_token(url)
        if token:
            try:
                return await self._scrape_via_api(token, progress_callback, images_only)
            except Exception:
                logger.exception("iCloud CloudKit API scrape failed, falling back to Selenium")

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as executor:
            return await loop.run_in_executor(
                executor, self._scrape_sync, url, progress_callback
            )

    @staticmethod
    def _extract_share_token(url: str) -> str | None:
        m = _SHARE_TOKEN_RE.search(url or "")
        return m.group(1) if m else None

    # ── CloudKit API 경로 ────────────────────────────────────────────────────

    async def _scrape_via_api(
        self, token: str, progress_callback=None, images_only: bool = False
    ) -> list[MediaItem]:
        if progress_callback:
            progress_callback({"step": "page_loading"})

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            # 1) shortGUID 해석 → zoneID + 익명 접근 토큰
            resolve = await client.post(
                f"{_CK_BASE}/public/records/resolve"
                "?remapEnums=true&getCurrentSyncToken=true",
                headers=_CK_HEADERS,
                content=f'{{"shortGUIDs":[{{"value":"{token}"}}]}}',
            )
            resolve.raise_for_status()
            results = (resolve.json() or {}).get("results") or []
            if not results:
                logger.warning("iCloud resolve returned no results for token=%s", token)
                return []
            result = results[0]
            zone_id = result.get("zoneID")
            access = (result.get("anonymousPublicAccess") or {}).get("token")
            if not zone_id or not access:
                # 로그인 필요 링크(requireAppleLogin) 등 — 익명 접근 불가
                logger.warning(
                    "iCloud share not anonymously accessible (token=%s, requireAppleLogin=%s)",
                    token, result.get("requireAppleLogin"),
                )
                return []

            if progress_callback:
                progress_callback({"step": "waiting_for_content"})

            # 2) 에셋 목록 조회 (continuationMarker로 페이지네이션)
            media_items: list[MediaItem] = []
            continuation = None
            for page in range(_MAX_PAGES):
                body: dict = {
                    "query": {
                        "recordType": _QUERY_RECORD_TYPE,
                        "filterBy": [
                            {
                                "fieldName": "direction",
                                "comparator": "EQUALS",
                                "fieldValue": {"value": "ASCENDING", "type": "STRING"},
                            }
                        ],
                    },
                    "zoneID": zone_id,
                    "resultsLimit": _PAGE_SIZE,
                }
                if continuation:
                    body["continuationMarker"] = continuation

                resp = await client.post(
                    f"{_CK_BASE}/shared/records/query"
                    f"?remapEnums=true&getCurrentSyncToken=true&publicAccessAuthToken={access}",
                    headers=_CK_HEADERS,
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json() or {}
                records = data.get("records") or []
                if not records:
                    break

                self._collect_api_records(records, media_items, images_only)

                if progress_callback:
                    progress_callback({
                        "step": "scrolling",
                        "current": page + 1,
                        "total": page + 2 if data.get("continuationMarker") else page + 1,
                    })

                continuation = data.get("continuationMarker")
                if not continuation:
                    break

            if progress_callback:
                progress_callback({"step": "collecting_media", "found": len(media_items)})
            logger.info("iCloud API scrape: %d items (token=%s)", len(media_items), token)
            return media_items

    @staticmethod
    def _collect_api_records(
        records: list[dict], media_items: list[MediaItem], images_only: bool
    ) -> None:
        """CPLMaster 레코드에서 MediaItem 생성.

        한 에셋은 CPLMaster(원본 리소스) + CPLAsset(메타) 쌍으로 오며,
        다운로드 URL은 CPLMaster에만 있다.
        """
        for rec in records:
            if rec.get("recordType") != "CPLMaster":
                continue
            fields = rec.get("fields") or {}
            item_type = fields.get("itemType", {}).get("value", "")
            is_video = _is_video(item_type)
            if is_video and images_only:
                continue

            filename = _decode_b64_field(fields, "filenameEnc")
            # 썸네일: 작은 JPEG → 중간 JPEG 순으로 폴백
            thumb = (
                _asset_url(fields, "resJPEGThumbRes", filename)
                or _asset_url(fields, "resJPEGMedRes", filename)
            )
            if is_video:
                # 영상 원본은 resOriginalRes(mp4). 없으면 트랜스코딩본 폴백.
                original = (
                    _asset_url(fields, "resOriginalRes", filename)
                    or _asset_url(fields, "resVidMedRes", filename)
                    or _asset_url(fields, "resVidSmallRes", filename)
                )
            else:
                original = (
                    _asset_url(fields, "resJPEGMedRes", filename)
                    or _asset_url(fields, "resOriginalRes", filename)
                    or thumb
                )
            if not original:
                continue

            media_items.append(
                MediaItem(
                    type=MediaType.VIDEO if is_video else MediaType.IMAGE,
                    thumbnail_url=thumb or original,
                    original_url=original,
                )
            )

    # ── 구형 공유앨범(Selenium) 경로 ─────────────────────────────────────────

    def _scrape_sync(self, url: str, progress_callback=None) -> list[MediaItem]:
        self._init_driver()
        try:
            if progress_callback:
                progress_callback({"step": "page_loading"})
            self.driver.get(url)
            time.sleep(8)

            if progress_callback:
                progress_callback({"step": "waiting_for_content"})
            # Wait for the first photo group to render
            try:
                WebDriverWait(self.driver, 20).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, ".x-stream-photo-group-view")
                    )
                )
            except Exception:
                pass

            # Scroll each group into view and collect images immediately
            # (iCloud virtualizes DOM — images are removed when scrolled away)
            media_items = []
            seen = set()
            self._scroll_and_collect(media_items, seen, progress_callback)

            if progress_callback:
                progress_callback({"step": "collecting_media", "found": len(media_items)})

            return media_items
        finally:
            self._quit_driver()

    def _resolve_image_url(self, src: str) -> str | None:
        """Convert blob URL to R2 URL, or return CDN URL as-is."""
        if src.startswith("blob:"):
            return self._upload_blob_to_r2(src)
        return src

    def _collect_visible_images(self, container, media_items: list, seen: set):
        """Collect iCloud content images from a visible DOM container."""
        imgs = container.find_elements(By.TAG_NAME, "img")
        for img in imgs:
            src = img.get_attribute("src") or ""
            if not src:
                continue
            if ("icloud-content.com" in src or src.startswith("blob:")) and src not in seen:
                seen.add(src)
                url = self._resolve_image_url(src)
                if url:
                    media_items.append(
                        MediaItem(type=MediaType.IMAGE, thumbnail_url=url, original_url=url)
                    )

    def _scroll_and_collect(self, media_items: list, seen: set, progress_callback=None):
        """Two-phase scroll: activate each group, then collect from each item.

        iCloud virtualizes the DOM at two levels:
        1. Group blocks with class 'not-visible' have no child grid items
        2. Grid items only render <img> tags when scrolled into view
        """
        groups = self.driver.find_elements(
            By.CSS_SELECTOR, ".x-stream-photo-group-block-view"
        )
        # Process in reverse order (bottom→top) so large grid groups
        # are handled first, before iCloud's image view recycling
        # interferes with smaller groups loaded earlier.
        for gi in reversed(range(len(groups))):
            group = groups[gi]
            # Activate group
            self.driver.execute_script(
                "arguments[0].scrollIntoView({behavior:'instant',block:'start'});",
                group,
            )
            time.sleep(3)
            for _ in range(10):
                if "not-visible" not in (group.get_attribute("class") or ""):
                    break
                time.sleep(0.5)

            # Scroll each grid item into center and collect
            items = group.find_elements(
                By.CSS_SELECTOR, ".x-stream-photo-grid-item-view"
            )
            for item in items:
                self.driver.execute_script(
                    "arguments[0].scrollIntoView({behavior:'instant',block:'center'});",
                    item,
                )
                for _ in range(8):
                    if item.find_elements(By.TAG_NAME, "img"):
                        break
                    time.sleep(0.5)
                self._collect_visible_images(item, media_items, seen)

            if progress_callback:
                progress_callback({
                    "step": "scrolling",
                    "current": len(groups) - gi,
                    "total": len(groups),
                })

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
