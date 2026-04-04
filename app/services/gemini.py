from google import genai
from google.genai import types

from app.config import settings

MIME_TO_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}


class GeminiService:
    def __init__(self):
        self.client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)

    async def generate_cover_image(
        self,
        prompt: str,
        reference_image_bytes: bytes,
    ) -> tuple[bytes, str, str]:
        """Gemini generate_content()로 참고 이미지 기반 커버 생성.

        Returns:
            (image_bytes, mime_type, extension)
        """
        response = await self.client.aio.models.generate_content(
            model="gemini-3.1-flash-image-preview",
            contents=[
                prompt,
                types.Part.from_bytes(
                    data=reference_image_bytes, mime_type="image/png"
                ),
            ],
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
            ),
        )
        for part in response.candidates[0].content.parts:
            if part.inline_data is not None:
                mime = part.inline_data.mime_type or "image/png"
                ext = MIME_TO_EXT.get(mime, "png")
                return part.inline_data.data, mime, ext
        raise RuntimeError("Gemini 응답에 이미지가 포함되지 않았습니다")
