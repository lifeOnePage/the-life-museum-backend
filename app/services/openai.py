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
