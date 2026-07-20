"""
Единый интерфейс для всех агентов — не зависит от того, какой провайдер ИИ используется.
Переключается через .env: LLM_PROVIDER=gemini или LLM_PROVIDER=openai

Все агенты (extractor, scam_detector, response_agent) импортируют функции ОТСЮДА,
а не напрямую из gemini_client/openai_client — так провайдера можно поменять
в одном месте, без правки кода агентов.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")  # всегда ищем .env рядом с этим файлом, независимо от CWD

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower()


class LLMError(Exception):
    pass


def call_llm(prompt: str, system_instruction: str | None = None,
             json_mode: bool = False, temperature: float = 0.7) -> str:
    if LLM_PROVIDER == "openai":
        from openai_client import call_openai, OpenAIError
        try:
            return call_openai(prompt, system_instruction, json_mode, temperature)
        except OpenAIError as e:
            raise LLMError(str(e)) from e
    else:
        from gemini_client import call_gemini, GeminiError
        try:
            return call_gemini(prompt, system_instruction, json_mode, temperature)
        except GeminiError as e:
            raise LLMError(str(e)) from e


def call_llm_json(prompt: str, system_instruction: str | None = None) -> dict:
    if LLM_PROVIDER == "openai":
        from openai_client import call_openai_json, OpenAIError
        try:
            return call_openai_json(prompt, system_instruction)
        except OpenAIError as e:
            raise LLMError(str(e)) from e
    else:
        from gemini_client import call_gemini_json, GeminiError
        try:
            return call_gemini_json(prompt, system_instruction)
        except GeminiError as e:
            raise LLMError(str(e)) from e
