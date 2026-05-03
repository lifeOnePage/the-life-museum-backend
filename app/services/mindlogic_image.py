import base64
import logging
from urllib.parse import urlparse

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

MIME_TO_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}


class MindlogicImageService:
    MODEL = "imagen-3.0-capability-001"

    def __init__(self):
        # GATEWAY_BASE_URL에서 host 추출: "https://factchat-cloud.mindlogic.ai/v1/gateway" → "https://factchat-cloud.mindlogic.ai"
        parsed = urlparse(settings.GATEWAY_BASE_URL)
        host = f"{parsed.scheme}://{parsed.netloc}"
        self.endpoint = f"{host}/v1/api/google/models/edit-image"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {settings.GATEWAY_API_KEY}",
            "Content-Type": "application/json",
        }

    async def generate_edit_image(
        self,
        prompt: str,
        reference_image_bytes: bytes,
        mime_type: str = "image/jpeg",
        reference_type: str = "REFERENCE_TYPE_STYLE",
    ) -> tuple[bytes, str, str]:
        """MindLogic API Gateway를 통해 Imagen edit-image를 호출한다.

        Returns:
            (image_bytes, mime_type, extension)
        """
        encoded = base64.b64encode(reference_image_bytes).decode("ascii")

        payload = {
            "model": self.MODEL,
            "prompt": prompt,
            "reference_images": [
                {
                    "reference_id": 1,
                    "reference_type": reference_type,
                    "image_bytes": encoded,
                    "mime_type": mime_type,
                }
            ],
            "config": {
                "number_of_images": 1,
                "output_mime_type": "image/png",
            },
        }

        logger.info(
            "MindLogic edit-image | model=%s | ref_type=%s | prompt=%r",
            self.MODEL,
            reference_type,
            prompt[:120],
        )

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                self.endpoint,
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        # 전체 응답 구조를 로깅 (테스트 단계에서 실제 포맷 파악용)
        logger.info("MindLogic edit-image raw response keys: %s", list(data.keys()))
        logger.debug("MindLogic edit-image full response: %s", data)

        # 응답 파싱: 여러 가능한 형식을 시도
        image_b64 = self._extract_image_b64(data)
        if not image_b64:
            raise RuntimeError(
                f"MindLogic 응답에서 이미지를 추출할 수 없습니다. keys={list(data.keys())}"
            )

        image_bytes = base64.b64decode(image_b64)
        out_mime = "image/png"
        ext = MIME_TO_EXT.get(out_mime, "png")

        logger.info(
            "MindLogic edit-image success: %d bytes, mime=%s", len(image_bytes), out_mime
        )
        return image_bytes, out_mime, ext

    @staticmethod
    def _extract_image_b64(data: dict) -> str | None:
        """여러 가능한 응답 포맷에서 base64 이미지 문자열을 추출한다."""
        # 형식 1: predictions[].bytesBase64Encoded (Imagen API 표준)
        predictions = data.get("predictions")
        if isinstance(predictions, list) and predictions:
            b64 = predictions[0].get("bytesBase64Encoded")
            if b64:
                return b64

        # 형식 2: generated_images[].image.image_bytes (Vertex AI 스타일)
        generated = data.get("generated_images") or data.get("generatedImages")
        if isinstance(generated, list) and generated:
            img = generated[0]
            # nested: generated_images[0].image.image_bytes
            inner = img.get("image", img)
            for key in ("image_bytes", "imageBytes", "bytesBase64Encoded"):
                b64 = inner.get(key)
                if b64:
                    return b64

        # 형식 3: images[].bytesBase64Encoded
        images = data.get("images")
        if isinstance(images, list) and images:
            item = images[0]
            if isinstance(item, str):
                return item
            if isinstance(item, dict):
                return item.get("bytesBase64Encoded") or item.get("image_bytes")

        # 형식 4: 단일 image 필드
        if "image" in data and isinstance(data["image"], str):
            return data["image"]

        return None
