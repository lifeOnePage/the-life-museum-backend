import base64
import io

from openai import AsyncOpenAI

from app.config import settings


class OpenAIService:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def generate_lifestory(self, qa_list: list[dict], mood: str) -> str:
        qa_text = "\n".join(
            f"Q: {qa['question']}\nA: {qa['answer']}" for qa in qa_list
        )

        prompt = f"""당신은 한 사람의 인생 이야기를 감동적으로 작성하는 전문 작가입니다.
아래 질문과 답변을 바탕으로 '{mood}' 분위기의 생애문을 작성해주세요.

[질문과 답변]
{qa_text}

[요구사항]
- 분위기: {mood}
- 300자 이내로 작성
- 한국어로 작성
- 따뜻하고 감동적인 어조로 작성
"""

        response = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "당신은 생애문 작성 전문가입니다."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=500,
            temperature=0.7,
        )

        return response.choices[0].message.content.strip()

    async def generate_cover_image(
        self,
        prompt: str,
        reference_image_bytes: bytes,
    ) -> bytes:
        """gpt-image-1 images.edit()로 참고 이미지 기반 커버 생성."""
        image_file = io.BytesIO(reference_image_bytes)
        image_file.name = "reference.png"

        result = await self.client.images.edit(
            model="gpt-image-1",
            image=image_file,
            prompt=prompt,
            n=1,
            size="1024x1024",
        )
        return base64.b64decode(result.data[0].b64_json)

    async def generate_story(
        self,
        prompt: str,
        album_title: str | None = None,
        album_subtitle: str | None = None,
    ) -> str:
        system_prompt = f"""당신은 앨범 뒷면에 들어갈 짧은 글을 작성하는 작가입니다.
사용자가 입력한 키워드나 문장을 바탕으로, 앨범에 기록할 감성적인 글을 작성합니다.

{f"앨범 제목: {album_title}" if album_title else ""}
{f"앨범 부제목: {album_subtitle}" if album_subtitle else ""}

사용자 입력: {prompt}

- 과업
3~5문장, 공백 포함 300자 이내로 작성합니다.
감성적이되 과장하지 마세요. 입력된 키워드와 내용을 자연스럽게 엮어 하나의 짧은 글로 만드세요.
입력에 없는 구체적 사실은 창작하지 마세요.
문장은 반드시 "~했다", "~이다", "~였다", "~있었다" 형태의 평서형 종결어미로 끝내세요.
예시: "바다를 바라보며 오래 앉아 있었다.", "그 시간이 좋았다.", "모두 함께여서 따뜻했다."
절대 "~했어", "~이야", "~줬어", "~거야" 같은 반말 종결어미를 사용하지 마세요.
담담하고 따뜻한 어조로, 마치 일기의 한 구절처럼 조용히 기록하는 문체로 작성하세요.
클리셰, 느낌표, 해시태그, 인용부호, 말줄임표를 사용하지 마세요.

- 최종 출력 형식
본문 텍스트만 반환(제목, 머리말/꼬리말, 안내문, 따옴표 금지).
300자 이내인지 점검 후 필요 시 간결하게 재압축.
""".strip()

        response = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            max_tokens=500,
            temperature=0.7,
        )

        return response.choices[0].message.content.strip()
