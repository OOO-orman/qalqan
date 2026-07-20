"""
Report Agent.

Собирает структурированный отчёт по переписке: краткое описание, тип схемы,
уровень риска, найденные цифровые следы, связи с другими случаями, таймлайн.
Отчёт формируется в Markdown — его удобно скопировать/экспортировать в PDF/Word.
"""
import datetime
from sqlalchemy.orm import Session
from database import Conversation, Message, Entity
from agents.link_analysis import find_linked_conversations

ENTITY_LABELS = {
    "phone": "Телефон",
    "card": "Банковская карта",
    "telegram": "Telegram",
    "link": "Ссылка",
    "email": "Email",
    "crypto": "Криптокошелёк",
    "other": "Другое",
}


def generate_report(db: Session, conversation_id: int) -> str:
    conv: Conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise ValueError(f"Переписка {conversation_id} не найдена")

    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
        .all()
    )
    entities = db.query(Entity).filter(Entity.conversation_id == conversation_id).all()
    links = find_linked_conversations(db, conversation_id)

    lines = []
    lines.append(f"# Отчёт по инциденту №{conv.id}")
    lines.append("")
    lines.append(f"**Дата формирования:** {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"**Собеседник (Telegram):** {conv.tg_display_name or '—'} "
                  f"(@{conv.tg_username or '—'}, id: {conv.tg_user_id or '—'})")
    lines.append("")
    lines.append("## Краткое описание")
    lines.append(conv.red_flags and "" or "")
    lines.append(f"**Тип мошенничества:** {conv.scam_type or 'не определён'}")
    lines.append(f"**Уровень риска:** {conv.risk_level}/10")
    lines.append("")

    if conv.red_flags:
        lines.append("**Признаки мошенничества:**")
        try:
            import json
            flags = json.loads(conv.red_flags)
            for f in flags:
                lines.append(f"- {f}")
        except Exception:
            lines.append(f"- {conv.red_flags}")
        lines.append("")

    lines.append("## Найденные цифровые следы")
    if entities:
        by_type: dict[str, list[str]] = {}
        for e in entities:
            by_type.setdefault(e.entity_type, []).append(e.value)
        for etype, values in by_type.items():
            label = ENTITY_LABELS.get(etype, etype)
            lines.append(f"**{label}:** " + ", ".join(sorted(set(values))))
    else:
        lines.append("_Цифровые следы не найдены._")
    lines.append("")

    lines.append("## Связи с другими случаями")
    if links:
        for link in links:
            matched = ", ".join(f"{ENTITY_LABELS.get(m['type'], m['type'])}: {m['value']}" for m in link["matched_on"])
            lines.append(f"- Переписка №{link['conversation_id']} — совпадение по: {matched}")
    else:
        lines.append("_Совпадений с другими случаями не найдено._")
    lines.append("")

    lines.append("## Временная шкала переписки")
    for m in messages:
        who = "Мошенник" if m.direction == "incoming" else "Персонаж (наш агент)"
        ts = m.created_at.strftime("%Y-%m-%d %H:%M") if m.created_at else "—"
        lines.append(f"- `{ts}` **{who}:** {m.text}")
    lines.append("")

    lines.append("---")
    lines.append("_Отчёт сформирован автоматически системой Qalqan для дальнейшей проверки "
                  "службой безопасности банка или правоохранительными органами._")

    return "\n".join(lines)
