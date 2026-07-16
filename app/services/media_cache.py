"""스크랩된 mediaList의 프로세스 로컬 TTL 캐시.

미디어 조회가 매 요청 원본 공유앨범을 재스크래핑하는 비용(특히 Selenium 기반
iCloud/MyBox)을 줄이기 위한 캐시. 다음 가드레일을 전제로 설계됨:

- 소스별 차등 TTL: 캐시하는 것은 외부 CDN URL 문자열이므로 TTL이 URL 수명을
  넘으면 프론트에서 이미지가 깨진다. iCloud/MyBox는 서명된 단기 URL이라 짧게,
  Google 계열(lh3)은 길게 잡고, 엔트리 TTL은 포함된 소스 중 가장 짧은 값.
- 부분 실패는 단기 TTL: 스크래핑은 소스 실패를 삼키고 나머지만 반환하므로,
  반쪽짜리 결과가 TTL 내내 고정되지 않도록 실패 포함 결과는 짧게만 캐시.
  빈 결과도 파싱 실패와 구분할 수 없어 동일하게 취급.
- 스크랩 원본 결과만 캐시: VideoCache(트랜스코딩 R2 URL) 교체는 캐시 히트
  시에도 호출부에서 매번 수행해야 한다. 여기서 교체 후 결과를 저장하면
  나중에 완료된 트랜스코딩이 TTL 동안 반영되지 않는다.
- single-flight: 같은 (record_id, images_only) 동시 요청은 진행 중인 스크랩
  하나를 공유한다 (Selenium 중복 실행 방지).

프로세스 로컬(단일 워커 전제)이며 멀티 워커/인스턴스 배포에서는 워커별로
독립이다. 그 규모가 되면 캐시를 Redis로 키우기보다 미디어 테이블 영속화로
전환할 것.
"""

import asyncio
import logging
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass

from app.schemas.scraper import MediaItem

logger = logging.getLogger(__name__)

# 소스별 TTL(초). 외부 CDN URL 수명보다 짧아야 한다.
_SOURCE_TTL_SECONDS = {
    "google_photos": 1800,
    "google_drive": 1800,
    "icloud": 300,
    "mybox": 300,
}
# 소스 실패 포함/빈 결과: 다음 재시도가 빨리 일어나도록 짧게만 캐시.
_DEGRADED_TTL_SECONDS = 120
_MAX_ENTRIES = 256


@dataclass
class _Entry:
    items: list[MediaItem]
    expires_at: float


class MediaListCache:
    def __init__(self) -> None:
        self._entries: OrderedDict[tuple[uuid.UUID, bool], _Entry] = OrderedDict()
        self._inflight: dict[tuple[uuid.UUID, bool], asyncio.Future] = {}

    def get(self, record_id: uuid.UUID, images_only: bool) -> list[MediaItem] | None:
        """유효한 캐시가 있으면 얕은 복사본을 반환. 만료/부재 시 None."""
        key = (record_id, images_only)
        entry = self._entries.get(key)
        if entry is None:
            return None
        if time.monotonic() >= entry.expires_at:
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return list(entry.items)

    def store(
        self,
        record_id: uuid.UUID,
        images_only: bool,
        items: list[MediaItem],
        providers: list[str],
        all_sources_ok: bool,
    ) -> None:
        if not providers:
            return
        if all_sources_ok and items:
            ttl = min(_SOURCE_TTL_SECONDS.get(p, _DEGRADED_TTL_SECONDS) for p in providers)
        else:
            ttl = _DEGRADED_TTL_SECONDS
        key = (record_id, images_only)
        self._entries[key] = _Entry(items=list(items), expires_at=time.monotonic() + ttl)
        self._entries.move_to_end(key)
        while len(self._entries) > _MAX_ENTRIES:
            self._entries.popitem(last=False)
        logger.info(
            "media_cache store record=%s images_only=%s items=%d ttl=%ds ok=%s",
            record_id, images_only, len(items), ttl, all_sources_ok,
        )

    def invalidate(self, record_id: uuid.UUID) -> None:
        for images_only in (True, False):
            self._entries.pop((record_id, images_only), None)

    async def get_or_scrape(
        self,
        record_id: uuid.UUID,
        images_only: bool,
        providers: list[str],
        scrape_fn,
    ) -> list[MediaItem]:
        """캐시 히트면 즉시 반환, 미스면 스크랩 후 저장.

        scrape_fn: () -> awaitable of (items, all_sources_ok).
        동일 키의 동시 호출은 첫 호출의 스크랩 결과를 공유한다.
        """
        cached = self.get(record_id, images_only)
        if cached is not None:
            return cached

        key = (record_id, images_only)
        existing = self._inflight.get(key)
        if existing is not None:
            return list(await asyncio.shield(existing))

        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._inflight[key] = fut
        try:
            items, all_sources_ok = await scrape_fn()
            self.store(record_id, images_only, items, providers, all_sources_ok)
            fut.set_result(items)
            return list(items)
        except BaseException as e:
            if not fut.cancelled():
                fut.set_exception(e)
                # 대기자가 없어도 "unretrieved exception" 경고가 뜨지 않도록 소비 처리
                fut.exception()
            raise
        finally:
            self._inflight.pop(key, None)


media_cache = MediaListCache()
