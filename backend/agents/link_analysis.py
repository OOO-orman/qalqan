"""
Link Analysis Agent.

Сравнивает извлечённые данные (телефоны, карты, telegram, ссылки, кошельки)
между разными переписками. Если значение встречается более чем в одной
переписке — это сигнал, что дела могут быть связаны (одна и та же
мошенническая сеть/человек).
"""
from sqlalchemy.orm import Session
from sqlalchemy import and_
from database import Entity


def find_linked_conversations(db: Session, conversation_id: int) -> list[dict]:
    """
    Возвращает список связанных переписок вида:
    [{"conversation_id": int, "matched_on": [{"type": str, "value": str}]}]
    """
    own_entities = db.query(Entity).filter(Entity.conversation_id == conversation_id).all()
    if not own_entities:
        return []

    links: dict[int, list[dict]] = {}
    for ent in own_entities:
        matches = (
            db.query(Entity)
            .filter(
                and_(
                    Entity.value == ent.value,
                    Entity.entity_type == ent.entity_type,
                    Entity.conversation_id != conversation_id,
                )
            )
            .all()
        )
        for m in matches:
            links.setdefault(m.conversation_id, [])
            links[m.conversation_id].append({"type": ent.entity_type, "value": ent.value})

    return [
        {"conversation_id": cid, "matched_on": matched}
        for cid, matched in links.items()
    ]
