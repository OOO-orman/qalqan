"""
Scam Detection Agent.

Анализирует всю переписку целиком и определяет:
 - является ли это мошенничеством
 - тип схемы
 - уровень риска (0-10)
 - признаки (red flags)
"""
from llm_client import call_llm_json, LLMError

SYSTEM_PROMPT = """Ты — аналитик кибербезопасности, специализирующийся на выявлении
мошеннических схем в переписках (дропперство, фишинг, инвестиционное мошенничество,
мошенничество с картами, вербовка через "лёгкую подработку" и т.д.), направленных на
подростков и молодёжь в Казахстане.

Тебе дают полную историю переписки между потенциальным мошенником и подростком.
Проанализируй её и верни строго валидный JSON (без markdown-обёртки) в формате:

{
  "is_scam": true/false,
  "scam_type": "краткое название типа схемы на русском (или null, если не мошенничество)",
  "risk_level": число от 0 до 10,
  "red_flags": ["список конкретных признаков, найденных в переписке"],
  "summary": "краткое описание сути происходящего в 2-3 предложениях"
}

Типичные типы схем: "вербовка дропперов", "инвестиционное мошенничество", "фишинг",
"мошенничество с банковскими картами", "романтическое мошенничество", "другое".
Если признаков мошенничества нет — is_scam: false, risk_level: 0.
"""


def analyze_conversation(messages: list[dict]) -> dict:
    """
    messages: список {"direction": "incoming"/"outgoing", "text": str}
    Возвращает dict с ключами is_scam, scam_type, risk_level, red_flags, summary.
    """
    transcript = "\n".join(
        f"{'МОШЕННИК' if m['direction'] == 'incoming' else 'ПОДРОСТОК'}: {m['text']}"
        for m in messages
    )
    prompt = f"Переписка:\n{transcript}"

    try:
        result = call_llm_json(prompt, system_instruction=SYSTEM_PROMPT)
    except LLMError as e:
        return {
            "is_scam": None,
            "scam_type": None,
            "risk_level": 0,
            "red_flags": [],
            "summary": f"Не удалось выполнить анализ: {e}",
        }

    result.setdefault("is_scam", None)
    result.setdefault("scam_type", None)
    result.setdefault("risk_level", 0)
    result.setdefault("red_flags", [])
    result.setdefault("summary", "")
    return result
