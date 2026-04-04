from google import genai
from google.genai import types

from app.config import settings


class GeminiService:
    def __init__(self):
        self.client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)

    async def generate_cover_image(
        self,
        prompt: str,
        reference_image_bytes: bytes,
    ) -> bytes:
        """Gemini generate_content()로 참고 이미지 기반 커버 생성."""
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
                return part.inline_data.data
        raise RuntimeError("Gemini 응답에 이미지가 포함되지 않았습니다")
