import base64
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class StabilityService:
    API_BASE = "https://api.stability.ai/v2beta/stable-image/generate"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {settings.STABILITY_API_KEY}",
            "Accept": "application/json",
        }

    async def generate_image(
        self,
        prompt: str,
        reference_image_bytes: bytes | None = None,
        image_strength: float = 0.5,
    ) -> bytes:
        """Generate an image using Stability AI Stable Image Ultra (SD3.5).

        Args:
            prompt: Text prompt describing the desired image.
            reference_image_bytes: Optional reference image bytes for image-to-image.
            image_strength: 0.0 = creative, 1.0 = faithful to reference.
                Stability API uses 'strength' where 0 = keep original, 1 = fully new,
                so we convert: strength = 1.0 - user_strength.

        Returns:
            PNG image bytes (1:1 aspect ratio).
        """
        url = f"{self.API_BASE}/ultra"

        data = {
            "prompt": prompt,
            "output_format": "png",
            "aspect_ratio": "1:1",
        }

        files = {}

        if reference_image_bytes:
            strength = 1.0 - image_strength
            data["mode"] = "image-to-image"
            data["strength"] = str(strength)
            files["image"] = ("reference.png", reference_image_bytes, "image/png")

            logger.info(
                "Stability Ultra img2img | strength=%.2f (api=%.2f) | prompt=%r",
                image_strength,
                strength,
                prompt,
            )
        else:
            logger.info("Stability Ultra txt2img | prompt=%r", prompt)

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                url,
                headers=self._headers(),
                data=data,
                files=files if files else None,
            )

        if resp.status_code != 200:
            logger.error(
                "Stability API error %d: %s",
                resp.status_code,
                resp.text[:500],
            )
            raise RuntimeError(
                f"Stability AI API error: {resp.status_code} — {resp.text[:200]}"
            )

        result = resp.json()
        image_b64 = result.get("image")
        if not image_b64:
            raise ValueError("Stability AI returned no image data")

        return base64.b64decode(image_b64)
