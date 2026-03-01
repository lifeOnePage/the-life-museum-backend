import asyncio
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

REPLICATE_API_URL = "https://api.replicate.com/v1"

# minimax/video-01은 strength 파라미터를 지원하지 않으므로
# 강도에 따라 프롬프트에 지시어를 추가하는 방식으로 대응한다.
_STRENGTH_LOW_SUFFIX = (
    ", loosely inspired by the reference image, prioritizing creative interpretation"
)
_STRENGTH_HIGH_SUFFIX = (
    ", closely following the visual style, composition, and color palette"
    " of the reference image throughout the entire video"
)


def _apply_image_strength(prompt: str, strength: float) -> str:
    """strength(0.0~1.0)에 따라 프롬프트에 참고 이미지 지시어를 추가한다.

    - 0.0 ~ 0.35 (낮음): 느슨하게 참고 → 모델이 프롬프트 위주로 생성
    - 0.35 ~ 0.65 (보통): 기본 동작, 수정 없음
    - 0.65 ~ 1.0 (높음): 스타일·구도를 가능한 한 유지하도록 지시
    """
    if strength < 0.35:
        return prompt + _STRENGTH_LOW_SUFFIX
    if strength > 0.65:
        return prompt + _STRENGTH_HIGH_SUFFIX
    return prompt


class ReplicateService:
    MODEL = "minimax/video-01"
    POLL_INTERVAL = 2   # seconds between polls
    MAX_POLLS = 150     # 150 × 2s = 300s (5 minutes)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Token {settings.REPLICATE_API_TOKEN}",
            "Content-Type": "application/json",
        }

    async def generate_video(
        self,
        prompt: str,
        reference_image_url: str | None = None,
        image_strength: float = 0.5,
    ) -> bytes:
        """Generate a short video from a text prompt (+ optional first frame).

        Args:
            prompt: 텍스트 프롬프트
            reference_image_url: 참고 이미지 R2 URL (선택)
            image_strength: 참고 이미지 반영 강도 0.0~1.0 (기본 0.5)
                            minimax/video-01이 strength 파라미터를 미지원하므로
                            프롬프트 지시어로 간접 제어한다.

        Returns:
            raw MP4 bytes
        """
        effective_prompt = prompt
        if reference_image_url:
            effective_prompt = _apply_image_strength(prompt, image_strength)

        input_payload: dict = {"prompt": effective_prompt}
        if reference_image_url:
            input_payload["first_frame_image"] = reference_image_url

        logger.info(
            "Replicate generate_video | model=%s | strength=%.2f | prompt=%r",
            self.MODEL,
            image_strength if reference_image_url else 0.0,
            effective_prompt,
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            # 1. Create prediction
            resp = await client.post(
                f"{REPLICATE_API_URL}/models/{self.MODEL}/predictions",
                headers=self._headers(),
                json={"input": input_payload},
            )
            resp.raise_for_status()
            prediction = resp.json()
            prediction_id = prediction["id"]
            logger.info("Replicate prediction created: %s", prediction_id)

            # 2. Poll until succeeded / failed (max 5 minutes)
            for attempt in range(self.MAX_POLLS):
                await asyncio.sleep(self.POLL_INTERVAL)
                poll_resp = await client.get(
                    f"{REPLICATE_API_URL}/predictions/{prediction_id}",
                    headers=self._headers(),
                )
                poll_resp.raise_for_status()
                data = poll_resp.json()
                status = data.get("status")
                logger.debug(
                    "Replicate poll %d/%d prediction=%s status=%s",
                    attempt + 1,
                    self.MAX_POLLS,
                    prediction_id,
                    status,
                )

                if status == "succeeded":
                    output = data.get("output")
                    video_url: str | None = None
                    if isinstance(output, list) and output:
                        video_url = output[0]
                    elif isinstance(output, str):
                        video_url = output
                    if not video_url:
                        raise ValueError(
                            f"Replicate succeeded but no output URL: {data}"
                        )

                    # 3. Download video bytes
                    dl_resp = await client.get(video_url, timeout=60.0)
                    dl_resp.raise_for_status()
                    return dl_resp.content

                if status in ("failed", "canceled"):
                    error_msg = data.get("error", "unknown error")
                    raise RuntimeError(
                        f"Replicate prediction {prediction_id} {status}: {error_msg}"
                    )

            raise TimeoutError(
                f"Replicate prediction {prediction_id} did not complete within "
                f"{self.MAX_POLLS * self.POLL_INTERVAL}s"
            )
