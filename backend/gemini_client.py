"""
Тонкая обёртка над Google Gemini API (REST), без тяжёлых SDK-зависимостей.
Используется всеми агентами: Scam Detector, Response Agent, Extractor (доп. проверка).
"""
import os
import json
import httpx
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")  # всегда ищем .env рядом с этим файлом, независимо от CWD

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash")
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiError(Exception):
    pass


def _endpoint() -> str:
    return f"{BASE_URL}/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"


def call_gemini(prompt: str, system_instruction: str | None = None,
                json_mode: bool = False, temperature: float = 0.7) -> str:
    """
    Отправляет запрос в Gemini и возвращает текст ответа.
    Если json_mode=True — просит модель вернуть строго валидный JSON (без ```-обёртки).
    """
    if not GEMINI_API_KEY:
        raise GeminiError(
            "GEMINI_API_KEY не задан. Заполните .env файл (см. .env.example)."
        )

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 1024,
        },
    }
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
    if json_mode:
        payload["generationConfig"]["response_mime_type"] = "application/json"

    try:
        resp = httpx.post(_endpoint(), json=payload, timeout=30.0)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise GeminiError(f"Ошибка Gemini API: {e.response.status_code} {e.response.text}") from e
    except httpx.RequestError as e:
        raise GeminiError(f"Не удалось подключиться к Gemini API: {e}") from e

    data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise GeminiError(f"Неожиданный формат ответа Gemini: {data}") from e


def call_gemini_json(prompt: str, system_instruction: str | None = None) -> dict:
    """Вызов Gemini с гарантированным парсингом JSON-ответа."""
    raw = call_gemini(prompt, system_instruction=system_instruction, json_mode=True, temperature=0.3)
    # На случай если модель всё же обернёт в ```json ... ```
    cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise GeminiError(f"Gemini вернул невалидный JSON: {raw}") from e
