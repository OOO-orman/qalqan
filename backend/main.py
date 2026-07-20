"""
Qalqan backend.

Оркестрирует весь пайплайн: входящее сообщение из Telegram -> извлечение данных ->
определение схемы мошенничества -> генерация черновика ответа -> уведомление дашборда.
Отправка сообщений происходит только по явному запросу оператора через REST API.
"""
import os
import json
import asyncio
import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import init_db, get_db, Conversation, Message, Entity, Report
import telegram_client
from agents.extractor import extract_entities
from agents.scam_detector import analyze_conversation
from agents.response_agent import suggest_reply
from agents.link_analysis import find_linked_conversations
from agents.report_generator import generate_report

app = FastAPI(title="Qalqan API")

ADMIN_TELEGRAM_USERNAME = os.getenv("ADMIN_TELEGRAM_USERNAME", "").lstrip("@")
HIGH_RISK_THRESHOLD = int(os.getenv("HIGH_RISK_THRESHOLD", "7"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# WebSocket-рассылка для дашборда в реальном времени
# ---------------------------------------------------------------------------
active_sockets: set[WebSocket] = set()


async def broadcast(event: dict):
    dead = []
    for ws in active_sockets:
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)
    for ws in dead:
        active_sockets.discard(ws)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_sockets.add(websocket)
    try:
        while True:
            await websocket.receive_text()  # держим соединение живым; входящие от клиента не используются
    except WebSocketDisconnect:
        active_sockets.discard(websocket)


# ---------------------------------------------------------------------------
# Пайплайн обработки нового входящего сообщения (вызывается из telegram_client)
# ---------------------------------------------------------------------------
def _history_for(db: Session, conversation_id: int) -> list[dict]:
    msgs = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .filter(Message.status.in_(["received", "sent", "edited_sent"]))
        .order_by(Message.created_at.asc())
        .all()
    )
    return [{"direction": m.direction, "text": m.text} for m in msgs]


async def _process_message(tg_user_id: str, username: Optional[str], display_name: str, text: str,
                            created_at: Optional[datetime.datetime] = None,
                            run_full_pipeline: bool = True):
    db = next(get_db())
    try:
        conv = db.query(Conversation).filter(Conversation.tg_user_id == tg_user_id).first()
        if not conv:
            conv = Conversation(tg_user_id=tg_user_id, tg_username=username, tg_display_name=display_name)
            db.add(conv)
            db.commit()
            db.refresh(conv)

        incoming = Message(
            conversation_id=conv.id, direction="incoming", text=text, status="received",
            created_at=created_at or datetime.datetime.utcnow(),
        )
        db.add(incoming)
        db.commit()
        db.refresh(incoming)

        # 1. Извлечение данных.
        # При обычном (живом) сообщении — regex + доп. проверка через ИИ (надёжнее).
        # При массовом импорте истории — только regex для всех сообщений, кроме
        # последнего в переписке, иначе на сотни старых сообщений уйдёт слишком
        # много обращений к ИИ и это будет очень медленно/дорого.
        found = extract_entities(text, use_llm=run_full_pipeline)
        existing_values = {
            (e.entity_type, e.value)
            for e in db.query(Entity).filter(Entity.conversation_id == conv.id).all()
        }
        for etype, values in found.items():
            for v in values:
                if (etype, v) not in existing_values:
                    db.add(Entity(conversation_id=conv.id, entity_type=etype, value=v))
                    existing_values.add((etype, v))
        db.commit()

        if not run_full_pipeline:
            # Используется при пакетном импорте истории — не гоняем LLM на каждое
            # старое сообщение, только извлекаем данные. Полный анализ — на последнем.
            return conv, incoming, None

        # 2. Анализ схемы мошенничества (на основе всей истории)
        history = _history_for(db, conv.id)
        analysis = analyze_conversation(history)
        conv.is_scam = analysis.get("is_scam")
        conv.scam_type = analysis.get("scam_type")
        conv.risk_level = analysis.get("risk_level") or 0
        conv.red_flags = json.dumps(analysis.get("red_flags") or [], ensure_ascii=False)
        db.commit()

        # 3. Черновик ответа для оператора
        draft_text = suggest_reply(history)
        draft = Message(conversation_id=conv.id, direction="outgoing", text=draft_text, status="suggested")
        db.add(draft)
        db.commit()
        db.refresh(draft)

        await broadcast({
            "type": "new_message",
            "conversation_id": conv.id,
            "incoming_message_id": incoming.id,
            "draft_message_id": draft.id,
            "risk_level": conv.risk_level,
            "scam_type": conv.scam_type,
        })
        return conv, incoming, draft
    finally:
        db.close()


async def handle_incoming_message(tg_user_id: str, username: Optional[str], display_name: str, text: str):
    await _process_message(tg_user_id, username, display_name, text)


telegram_client.on_incoming_message = handle_incoming_message


@app.post("/telegram/import-history")
async def import_history(limit_per_chat: int = 200, hours_back: int = 24):
    """
    Импортирует переписки НЕ СТАРШЕ hours_back часов (по умолчанию — за последние сутки).
    Чтобы импортировать вообще всю историю без ограничения по дате — передайте hours_back=0.
    """
    since = None
    if hours_back and hours_back > 0:
        since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours_back)

    try:
        messages = await telegram_client.import_history(limit_per_chat=limit_per_chat, since=since)
    except Exception as e:
        raise HTTPException(400, f"Не удалось импортировать историю: {e}")

    # Группируем по собеседнику, сохраняя хронологический порядок
    by_user: dict[str, list[dict]] = {}
    for m in messages:
        by_user.setdefault(m["tg_user_id"], []).append(m)

    imported_conversations = 0
    for tg_user_id, msgs in by_user.items():
        for i, m in enumerate(msgs):
            is_last = (i == len(msgs) - 1)
            await _process_message(
                tg_user_id=tg_user_id,
                username=m["username"],
                display_name=m["display_name"],
                text=m["text"],
                created_at=m["created_at"],
                run_full_pipeline=is_last,
            )
        imported_conversations += 1

    return {"ok": True, "conversations_imported": imported_conversations, "messages_imported": len(messages)}


# ---------------------------------------------------------------------------
# Telegram: авторизация
# ---------------------------------------------------------------------------
class RequestCodeBody(BaseModel):
    phone: str


class ConfirmCodeBody(BaseModel):
    phone: str
    code: str
    phone_code_hash: str
    password: Optional[str] = None


class AppConfigBody(BaseModel):
    api_id: str
    api_hash: str
    phone: Optional[str] = None


@app.get("/telegram/app-config-status")
def telegram_app_config_status():
    return {"configured": telegram_client.app_credentials_configured()}


@app.post("/telegram/configure-app")
def telegram_configure_app(body: AppConfigBody):
    """
    Сохраняет TELEGRAM_API_ID / TELEGRAM_API_HASH (и телефон, если передан) в .env
    прямо с сайта, без ручного редактирования файлов. Эти значения — это ключ
    ПРИЛОЖЕНИЯ Qalqan (получаются один раз на my.telegram.org), их достаточно
    настроить один раз для всей системы.
    """
    try:
        telegram_client.save_app_credentials(body.api_id, body.api_hash, body.phone or "")
    except Exception as e:
        raise HTTPException(400, f"Не удалось сохранить настройки: {e}")
    return {"ok": True}


@app.get("/telegram/status")
async def telegram_status():
    return {"authorized": await telegram_client.is_authorized()}


@app.post("/telegram/request-code")
async def telegram_request_code(body: RequestCodeBody):
    try:
        phone_code_hash = await telegram_client.request_login_code(body.phone)
    except telegram_client.NotConfiguredError as e:
        raise HTTPException(409, str(e))
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"phone_code_hash": phone_code_hash}


@app.post("/telegram/confirm-code")
async def telegram_confirm_code(body: ConfirmCodeBody):
    try:
        me = await telegram_client.confirm_login_code(
            phone=body.phone, code=body.code,
            phone_code_hash=body.phone_code_hash, password=body.password,
        )
        await telegram_client.start_listening()
        asyncio.create_task(telegram_client.get_client().run_until_disconnected())
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "user_id": me.id, "username": me.username}


# ---------------------------------------------------------------------------
# Переписки
# ---------------------------------------------------------------------------
@app.get("/conversations")
def list_conversations(db: Session = Depends(get_db)):
    convs = db.query(Conversation).order_by(Conversation.updated_at.desc()).all()
    return {
        "high_risk_threshold": HIGH_RISK_THRESHOLD,
        "conversations": [
            {
                "id": c.id,
                "tg_username": c.tg_username,
                "tg_display_name": c.tg_display_name,
                "status": c.status,
                "scam_type": c.scam_type,
                "risk_level": c.risk_level,
                "is_scam": c.is_scam,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in convs
        ],
    }


@app.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: int, db: Session = Depends(get_db)):
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(404, "Переписка не найдена")
    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
        .all()
    )
    entities = db.query(Entity).filter(Entity.conversation_id == conversation_id).all()
    links = find_linked_conversations(db, conversation_id)

    return {
        "id": conv.id,
        "tg_username": conv.tg_username,
        "tg_display_name": conv.tg_display_name,
        "risk_level": conv.risk_level,
        "scam_type": conv.scam_type,
        "is_scam": conv.is_scam,
        "red_flags": json.loads(conv.red_flags) if conv.red_flags else [],
        "parent_contact": conv.parent_contact,
        "high_risk_threshold": HIGH_RISK_THRESHOLD,
        "admin_configured": bool(ADMIN_TELEGRAM_USERNAME),
        "messages": [
            {
                "id": m.id, "direction": m.direction, "text": m.text,
                "status": m.status, "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
        "entities": [
            {"id": e.id, "type": e.entity_type, "value": e.value} for e in entities
        ],
        "linked_conversations": links,
    }


class SendMessageBody(BaseModel):
    text: Optional[str] = None  # если None — отправляем текст черновика как есть


@app.post("/conversations/{conversation_id}/messages/{message_id}/send")
async def send_message(conversation_id: int, message_id: int, body: SendMessageBody,
                        db: Session = Depends(get_db)):
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    msg = db.query(Message).filter(Message.id == message_id, Message.conversation_id == conversation_id).first()
    if not conv or not msg:
        raise HTTPException(404, "Не найдено")
    if msg.status != "suggested":
        raise HTTPException(400, "Это сообщение уже обработано")

    final_text = body.text if body.text is not None else msg.text
    try:
        await telegram_client.send_message_to_user(conv.tg_user_id, final_text)
    except Exception as e:
        raise HTTPException(500, f"Не удалось отправить сообщение в Telegram: {e}")

    msg.text = final_text
    msg.status = "sent" if body.text is None else "edited_sent"
    db.commit()
    await broadcast({"type": "message_sent", "conversation_id": conversation_id, "message_id": msg.id})
    return {"ok": True}


@app.post("/conversations/{conversation_id}/messages/{message_id}/skip")
def skip_message(conversation_id: int, message_id: int, db: Session = Depends(get_db)):
    msg = db.query(Message).filter(Message.id == message_id, Message.conversation_id == conversation_id).first()
    if not msg:
        raise HTTPException(404, "Не найдено")
    msg.status = "skipped"
    db.commit()
    return {"ok": True}


class UpdateContactBody(BaseModel):
    parent_contact: Optional[str] = None  # telegram username, можно с @ или без


@app.patch("/conversations/{conversation_id}")
def update_conversation(conversation_id: int, body: UpdateContactBody, db: Session = Depends(get_db)):
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(404, "Переписка не найдена")
    if body.parent_contact is not None:
        conv.parent_contact = body.parent_contact.lstrip("@") or None
    db.commit()
    return {"ok": True, "parent_contact": conv.parent_contact}


class SendReportBody(BaseModel):
    also_send_to_parent: bool = False


@app.post("/conversations/{conversation_id}/report/send")
async def send_report(conversation_id: int, body: SendReportBody, db: Session = Depends(get_db)):
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(404, "Переписка не найдена")

    if not ADMIN_TELEGRAM_USERNAME:
        raise HTTPException(
            400,
            "ADMIN_TELEGRAM_USERNAME не настроен в .env — некому отправлять отчёт. "
            "Укажите username админа Qalqan в файле .env и перезапустите сервер.",
        )

    try:
        content = generate_report(db, conversation_id)
    except ValueError as e:
        raise HTTPException(404, str(e))

    report = Report(
        conversation_id=conversation_id, content=content,
        risk_level=conv.risk_level, scam_type=conv.scam_type,
    )
    db.add(report)
    db.commit()

    results = {"admin": None, "parent": None}

    try:
        await telegram_client.send_message_to_username(ADMIN_TELEGRAM_USERNAME, content)
        results["admin"] = "ok"
    except Exception as e:
        results["admin"] = f"ошибка: {e}"

    if body.also_send_to_parent:
        if not conv.parent_contact:
            results["parent"] = "не указан контакт родителей для этой переписки"
        else:
            try:
                intro = (
                    "Здравствуйте! Это автоматическое уведомление системы Qalqan. "
                    "Ваш ребёнок мог стать целью мошеннической схемы в Telegram. "
                    "Ниже — подробности для вашей информации:\n\n"
                )
                await telegram_client.send_message_to_username(conv.parent_contact, intro + content)
                results["parent"] = "ok"
            except Exception as e:
                results["parent"] = f"ошибка: {e}"

    return {"ok": True, "results": results, "content": content}


@app.get("/conversations/{conversation_id}/report")
def get_report(conversation_id: int, db: Session = Depends(get_db)):
    try:
        content = generate_report(db, conversation_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    report = Report(
        conversation_id=conversation_id,
        content=content,
        risk_level=db.get(Conversation, conversation_id).risk_level,
        scam_type=db.get(Conversation, conversation_id).scam_type,
    )
    db.add(report)
    db.commit()
    return {"content": content}


# ---------------------------------------------------------------------------
# Старт приложения
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def on_startup():
    init_db()
    if await telegram_client.is_authorized():
        await telegram_client.start_listening()
        asyncio.create_task(telegram_client.get_client().run_until_disconnected())


# Раздаём фронтенд (папка ../frontend) с того же адреса, что и API —
# теперь дашборд открывается просто по http://127.0.0.1:8000, без
# необходимости вручную искать и открывать файл index.html.
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
