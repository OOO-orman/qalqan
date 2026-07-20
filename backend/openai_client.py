"""
Тонкая обёртка над OpenAI API (REST), по аналогии с gemini_client.py.
"""
import os
import json
import httpx
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")  # всегда ищем .env рядом с этим файлом, независимо от CWD

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
ENDPOINT = "https://api.openai.com/v1/chat/completions"


class OpenAIError(Exception):
    pass


def call_openai(prompt: str, system_instruction: str | None = None,
                 json_mode: bool = False, temperature: float = 0.7) -> str:
    if not OPENAI_API_KEY:
        raise OpenAIError("OPENAI_API_KEY не задан. Заполните .env файл.")

    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": OPENAI_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 1024,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    try:
        resp = httpx.post(
            ENDPOINT,
            json=payload,
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            timeout=30.0,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise OpenAIError(f"Ошибка OpenAI API: {e.response.status_code} {e.response.text}") from e
    except httpx.RequestError as e:
        raise OpenAIError(f"Не удалось подключиться к OpenAI API: {e}") from e

    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise OpenAIError(f"Неожиданный формат ответа OpenAI: {data}") from e


def call_openai_json(prompt: str, system_instruction: str | None = None) -> dict:
    raw = call_openai(prompt, system_instruction=system_instruction, json_mode=True, temperature=0.3)
    cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise OpenAIError(f"OpenAI вернул невалидный JSON: {raw}") from e
