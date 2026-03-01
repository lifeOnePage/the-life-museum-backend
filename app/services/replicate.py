import asyncio
import logging
import os
import tempfile

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

# 출력 해상도: minimax/video-01은 해상도 파라미터 미지원 → ffmpeg 후처리로 보장
OUTPUT_SIZE = 720


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


async def _crop_to_square(video_bytes: bytes, size: int = OUTPUT_SIZE) -> bytes:
    """ffmpeg로 비디오를 센터-크롭(1:1) 후 size×size로 리사이즈한다.

    처리 순서:
      1. 임시 파일에 원본 bytes 기록
      2. ffmpeg: crop=min(iw,ih):min(iw,ih) → scale=size:size
      3. 결과 bytes 반환
      4. 임시 파일 정리 (성공·실패 무관)

    ffmpeg 미설치 또는 오류 시 원본 bytes를 그대로 반환하고 경고 로그를 남긴다.
    """
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp.write(video_bytes)
        in_path = tmp.name

    out_path = in_path[:-4] + "_sq.mp4"

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-i", in_path,
            # 센터 기준 정사각 크롭 후 목표 해상도로 스케일
            "-vf", f"crop=min(iw\\,ih):min(iw\\,ih),scale={size}:{size}",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-an",           # 오디오 스트림 제거 (영상 전용)
            out_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.warning(
                "ffmpeg crop failed (rc=%d): %s",
                proc.returncode,
                stderr.decode(errors="replace"),
            )
            return video_bytes  # fallback: 원본 반환

        result_size = os.path.getsize(out_path)
        logger.info("ffmpeg crop succeeded → %dx%d, %d bytes", size, size, result_size)
        with open(out_path, "rb") as f:
            return f.read()

    except FileNotFoundError:
        logger.warning("ffmpeg not found; returning original video bytes as-is")
        return video_bytes

    finally:
        for path in (in_path, out_path):
            try:
                os.unlink(path)
            except OSError:
                pass


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

        Returns:
            720×720 MP4 bytes (ffmpeg 후처리 적용)
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

        raw_bytes: bytes | None = None

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

                    # 3. Download raw video bytes
                    dl_resp = await client.get(video_url, timeout=60.0)
                    dl_resp.raise_for_status()
                    raw_bytes = dl_resp.content
                    break  # exit poll loop

                if status in ("failed", "canceled"):
                    error_msg = data.get("error", "unknown error")
                    raise RuntimeError(
                        f"Replicate prediction {prediction_id} {status}: {error_msg}"
                    )

            else:
                raise TimeoutError(
                    f"Replicate prediction {prediction_id} did not complete within "
                    f"{self.MAX_POLLS * self.POLL_INTERVAL}s"
                )

        # 4. Crop + resize to 720×720 (httpx 클라이언트 닫힌 후 실행)
        return await _crop_to_square(raw_bytes)
