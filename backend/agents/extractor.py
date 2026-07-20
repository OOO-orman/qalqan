"""
Intelligence Agent (Extractor).

Извлекает из текста сообщения цифровые следы:
телефоны, банковские карты, telegram-аккаунты, ссылки, крипто-кошельки, email.

Стратегия: сначала быстрые и надёжные regex (без затрат на LLM),
затем (опционально) Gemini как подстраховка для нестандартных форм
(например, номер карты, написанный словами или с необычными разделителями).
"""
import re
from llm_client import call_llm_json, LLMError

PHONE_RE = re.compile(r"(?:\+?7|8)[\s\-\(]?\d{3}[\s\-\)]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}")
CARD_RE = re.compile(r"\b(?:\d[ -]?){16}\b")
TELEGRAM_RE = re.compile(r"(?:@[a-zA-Z0-9_]{4,32})|(?:t\.me/[a-zA-Z0-9_]{4,32})")
LINK_RE = re.compile(r"https?://[^\s]+|www\.[^\s]+")
EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
# BTC (legacy/P2SH/bech32), ETH/TRC20-like hex, TRON (Txxxx)
CRYPTO_RE = re.compile(
    r"\b(?:bc1[a-z0-9]{25,39}|[13][a-km-zA-HJ-NP-Z1-9]{25,34}|0x[a-fA-F0-9]{40}|T[a-zA-Z0-9]{33})\b"
)


def _clean(values: list[str]) -> list[str]:
    seen = set()
    out = []
    for v in values:
        v = v.strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def extract_with_regex(text: str) -> dict[str, list[str]]:
    return {
        "phone": _clean(PHONE_RE.findall(text)),
        "card": _clean(["".join(c for c in m if c.isdigit()) for m in CARD_RE.findall(text)]),
        "telegram": _clean(TELEGRAM_RE.findall(text)),
        "link": _clean(LINK_RE.findall(text)),
        "email": _clean(EMAIL_RE.findall(text)),
        "crypto": _clean(CRYPTO_RE.findall(text)),
    }


LLM_SYSTEM_PROMPT = (
    "Ты — модуль извлечения данных для системы кибербезопасности. "
    "Тебе дают одно сообщение из переписки. Твоя задача — найти в нём любые "
    "цифровые идентификаторы, которые НЕ являются стандартными телефонами/картами/ссылками "
    "(те уже найдены обычным поиском по шаблону), например: номера карт или телефонов, "
    "написанные словами или с необычными разделителями, названия банков с реквизитами, "
    "никнеймы в других соцсетях, номера кошельков. "
    "Верни строго JSON без пояснений в формате: "
    '{"phone": [], "card": [], "telegram": [], "link": [], "email": [], "crypto": [], "other": []}. '
    "Если ничего дополнительного не найдено — верни пустые списки."
)


def extract_with_llm(text: str) -> dict[str, list[str]]:
    try:
        result = call_llm_json(f"Сообщение:\n{text}", system_instruction=LLM_SYSTEM_PROMPT)
    except LLMError:
        # Если LLM недоступен — не роняем систему, просто работаем на regex
        return {}
    return result if isinstance(result, dict) else {}


def merge_entities(*dicts: dict[str, list[str]]) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for d in dicts:
        for k, values in d.items():
            merged.setdefault(k, [])
            merged[k].extend(values)
    for k in merged:
        merged[k] = _clean(merged[k])
    return merged


def extract_entities(text: str, use_llm: bool = True) -> dict[str, list[str]]:
    """Главная точка входа: возвращает словарь {тип: [значения]}."""
    regex_result = extract_with_regex(text)
    if not use_llm:
        return regex_result
    llm_result = extract_with_llm(text)
    return merge_entities(regex_result, llm_result)
