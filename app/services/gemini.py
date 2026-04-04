import base64

from google import genai
from google.genai import types

from app.config import settings

MIME_TO_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}

_IMAGE_MAGIC = [
    (b"\x89PNG", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"RIFF", "image/webp"),
]


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
                data = part.inline_data.data
                mime = part.inline_data.mime_type or "image/png"

                print(
                    f"[Gemini] inline_data: type={type(data).__name__}, "
                    f"len={len(data) if data else 0}, mime={mime}, "
                    f"head={data[:20]!r}"
                )

                # str → base64 디코딩
                if isinstance(data, str):
                    data = base64.b64decode(data)

                # bytes지만 매직 바이트가 없으면 base64 인코딩된 bytes일 수 있음
                if isinstance(data, bytes) and not self._has_image_magic(data):
                    try:
                        decoded = base64.b64decode(data)
                        if self._has_image_magic(decoded):
                            data = decoded
                            print(f"[Gemini] base64-decoded bytes, new len={len(data)}")
                    except Exception:
                        pass

                # 매직 바이트로 실제 포맷 확인
                for magic, detected_mime in _IMAGE_MAGIC:
                    if data[: len(magic)] == magic:
                        mime = detected_mime
                        break

                ext = MIME_TO_EXT.get(mime, "png")
                print(f"[Gemini] final: mime={mime}, ext={ext}, len={len(data)}")
                return data, mime, ext
        raise RuntimeError("Gemini 응답에 이미지가 포함되지 않았습니다")

    @staticmethod
    def _has_image_magic(data: bytes) -> bool:
        return any(data[: len(m)] == m for m, _ in _IMAGE_MAGIC)
