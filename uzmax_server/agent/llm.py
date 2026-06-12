import json
import os

from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()


def configured_secret(value: str | None) -> str | None:
    if not value:
        return None
    upper = value.upper()
    if any(marker in upper for marker in ("YOUR_", "YOUR-", "YOUR", "_HERE", "KEY_HERE")):
        return None
    return value


class OpenAIClient:
    """OpenAI-only LLM client for the UzMAX chatbot."""

    def __init__(self, api_key: str = None, model: str = None):
        openai_key = configured_secret(api_key or os.getenv("OPENAI_API_KEY"))
        self.client = AsyncOpenAI(api_key=openai_key) if openai_key else None
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    async def get_response_stream(self, messages: list):
        if self.client is None:
            yield "OpenAI API kaliti sozlanmagan. Iltimos, .env faylga haqiqiy OPENAI_API_KEY kiriting."
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
                        "Extract the person's first and last name from the phrase. "
                        "Return only JSON in this exact shape: "
                        '{"first_name":"...","last_name":"...","is_confident":true}. '
                        "If there is no last name, return an empty string for last_name. "
                        "If you are not confident, return is_confident=false. "
                        "Do not add markdown."
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0,
        )
        content = response.choices[0].message.content or "{}"
        content = content.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        try:
            data = json.loads(content)
        except Exception:
            return None
        if not data.get("first_name"):
            return None
        return data
