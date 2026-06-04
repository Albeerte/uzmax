import os
import json
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()


def configured_secret(value: str | None) -> str | None:
    if not value:
        return None
    upper = value.upper()
    if any(marker in upper for marker in ("YOUR_", "YOUR-", "YOUR", "_HERE", "KEY_HERE")):
        return None
    return value


class OpenAIClient:
    """
    LLM client that supports both OpenRouter and OpenAI.
    Priority:
      1. OPENROUTER_API_KEY  → routes to openrouter.ai (many free models)
      2. OPENAI_API_KEY      → routes to api.openai.com
    """

    def __init__(self, api_key: str = None, model: str = None):
        openrouter_key = configured_secret(os.getenv("OPENROUTER_API_KEY"))
        openai_key     = configured_secret(api_key or os.getenv("OPENAI_API_KEY"))

        if openrouter_key:
            self.client = AsyncOpenAI(
                api_key=openrouter_key,
                base_url="https://openrouter.ai/api/v1",
                default_headers={
                    "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "http://localhost:8000"),
                    "X-Title":     os.getenv("OPENROUTER_APP_NAME", "UzMAX Robot"),
                },
            )
            self.model = model or os.getenv(
                "OPENROUTER_MODEL",
                "google/gemini-2.0-flash-exp:free",
            )
        else:
            self.client = AsyncOpenAI(api_key=openai_key) if openai_key else None
            self.model  = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    async def get_response_stream(self, messages: list):
        if self.client is None:
            yield "OpenRouter yoki OpenAI API kaliti sozlanmagan. Iltimos, .env faylga haqiqiy kalit kiriting."
            return
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
        )
        async for chunk in response:
            if chunk.choices:
                content = chunk.choices[0].delta.content
                if content:
                    yield content

    async def extract_person_name(self, text: str) -> dict | None:
        if self.client is None:
            return None
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Извлеки имя и фамилию человека из фразы. "
                        "Верни только JSON вида "
                        '{"first_name":"...","last_name":"...","is_confident":true}. '
                        "Если фамилии нет, верни пустую строку. "
                        "Если не уверен, верни is_confident=false. "
                        "Не добавляй markdown, только чистый JSON."
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0,
        )
        content = response.choices[0].message.content or "{}"
        # Strip markdown code fences if model added them
        content = content.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        try:
            data = json.loads(content)
        except Exception:
            return None
        if not data.get("first_name"):
            return None
        return data
