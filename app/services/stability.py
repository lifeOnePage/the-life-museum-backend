import base64
import io
import logging

import httpx
from PIL import Image

from app.config import settings

logger = logging.getLogger(__name__)


SDXL_ALLOWED_DIMS = [
    (1024, 1024), (1152, 896), (1216, 832), (1344, 768), (1536, 640),
    (640, 1536), (768, 1344), (832, 1216), (896, 1152),
]


def _resize_for_sdxl(image_bytes: bytes) -> bytes:
    """Resize & crop image to the nearest allowed SDXL dimension.

    Crops the longer side (center crop) to match the target aspect ratio,
    then resizes to the exact allowed dimension.
    """
    img = Image.open(io.BytesIO(image_bytes))
    w, h = img.size
    aspect = w / h

    # Find the allowed dimension with the closest aspect ratio
    target_w, target_h = min(
        SDXL_ALLOWED_DIMS, key=lambda d: abs(d[0] / d[1] - aspect)
    )
    target_aspect = target_w / target_h

    # Center-crop to match target aspect ratio
    if aspect > target_aspect:
        # Too wide — crop sides
        new_w = int(h * target_aspect)
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    elif aspect < target_aspect:
        # Too tall — crop top/bottom
        new_h = int(w / target_aspect)
        top = (h - new_h) // 2
        img = img.crop((0, top, w, top + new_h))

    img = img.resize((target_w, target_h), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class StabilityService:
    ENGINE = "stable-diffusion-xl-1024-v1-0"
    API_BASE = "https://api.stability.ai/v1/generation"
    OUTPUT_SIZE = 1024

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
        """Generate an image using Stability AI SDXL.

        Args:
            prompt: Text prompt describing the desired image.
            reference_image_bytes: Optional reference image bytes for image-to-image.
            image_strength: 0.0 = creative, 1.0 = faithful to reference.
                Stability AI's parameter is inverted (0=keep original, 1=fully new),
                so we convert: stability_strength = 1.0 - user_strength.

        Returns:
            PNG image bytes.
        """
        async with httpx.AsyncClient(timeout=60.0) as client:
            if reference_image_bytes:
                # image-to-image: multipart/form-data
                stability_strength = 1.0 - image_strength
                url = f"{self.API_BASE}/{self.ENGINE}/image-to-image"

                resized = _resize_for_sdxl(reference_image_bytes)
                files = {
                    "init_image": ("reference.png", resized, "image/png"),
                }
                data = {
                    "text_prompts[0][text]": prompt,
                    "text_prompts[0][weight]": "1",
                    "image_strength": str(stability_strength),
                    "cfg_scale": "7",
                    "samples": "1",
                    "steps": "30",
                }

                logger.info(
                    "Stability img2img | strength=%.2f (stability=%.2f) | prompt=%r",
                    image_strength,
                    stability_strength,
                    prompt,
                )

                resp = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {settings.STABILITY_API_KEY}",
                        "Accept": "application/json",
                    },
                    files=files,
                    data=data,
                )
            else:
                # text-to-image: JSON body
                url = f"{self.API_BASE}/{self.ENGINE}/text-to-image"
                payload = {
                    "text_prompts": [{"text": prompt, "weight": 1}],
                    "cfg_scale": 7,
                    "width": self.OUTPUT_SIZE,
                    "height": self.OUTPUT_SIZE,
                    "samples": 1,
                    "steps": 30,
                }

                logger.info("Stability txt2img | prompt=%r", prompt)

                resp = await client.post(
                    url,
                    headers=self._headers(),
                    json=payload,
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
            artifacts = result.get("artifacts", [])
            if not artifacts:
                raise ValueError("Stability AI returned no artifacts")

            image_b64 = artifacts[0]["base64"]
            return base64.b64decode(image_b64)
