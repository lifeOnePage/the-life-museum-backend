import asyncio
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

REPLICATE_API_URL = "https://api.replicate.com/v1"


class ReplicateService:
    MODEL = "minimax/video-01"
    POLL_INTERVAL = 2  # seconds
    MAX_POLLS = 90  # 3 minutes max

    def _headers(self) -> dict:
        return {
            "Authorization": f"Token {settings.REPLICATE_API_TOKEN}",
            "Content-Type": "application/json",
        }

    async def generate_video(
        self, prompt: str, reference_image_url: str | None = None
    ) -> bytes:
        """Generate a short video from a text prompt (+ optional first frame).

        Returns raw video bytes on success, raises on error/timeout.
        """
        input_payload: dict = {"prompt": prompt}
        if reference_image_url:
            input_payload["first_frame_image"] = reference_image_url

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

            # 2. Poll until succeeded / failed
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
