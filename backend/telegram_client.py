"""
Telegram интеграция (Telethon).

ВАЖНО про модель безопасности:
 - Это НЕ автономный "userbot", рассылающий сообщения случайным людям.
 - Клиент логинится под ОДНИМ конкретным аккаунтом-приманкой, который вы сами
   контролируете (ваш номер или отдельная SIM, оформленная на вас/команду).
 - Скрипт только СЛУШАЕТ входящие личные сообщения (то есть реагирует, когда
   собеседник САМ пишет первым) и никогда не пишет мошеннику первым по своей инициативе.
 - Отправка исходящих сообщений происходит ТОЛЬКО через явный вызов send_message(),
   который вызывается из дашборда после подтверждения оператором (см. main.py).
"""
import os
import datetime
from telethon import TelegramClient, events
from telethon.tl.types import User
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")  # всегда ищем .env рядом с этим файлом, независимо от CWD

API_ID = int(os.getenv("TELEGRAM_API_ID", "0") or "0")
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
PHONE = os.getenv("TELEGRAM_PHONE", "")
SESSION_NAME = "qalqan_session"

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# Callback, который main.py подставит при старте — вызывается на каждое новое
# входящее личное сообщение. Сигнатура: async def(tg_user_id, username, display_name, text)
on_incoming_message = None


async def request_login_code(phone: str | None = None):
    """Шаг 1 авторизации: запросить код подтверждения на телефон."""
    await client.connect()
    phone = phone or PHONE
    sent = await client.send_code_request(phone)
    return sent.phone_code_hash


async def confirm_login_code(phone: str, code: str, phone_code_hash: str, password: str | None = None):
    """Шаг 2 авторизации: ввести код (и пароль 2FA, если включён)."""
    from telethon.errors import SessionPasswordNeededError
    try:
        await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
    except SessionPasswordNeededError:
        if not password:
            raise
        await client.sign_in(password=password)
    return await client.get_me()


async def is_authorized() -> bool:
    if not client.is_connected():
        await client.connect()
    return await client.is_user_authorized()


async def start_listening():
    """Регистрирует обработчик входящих личных сообщений и запускает клиента."""
    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        if not event.is_private:
            return  # игнорируем группы/каналы — работаем только с личными перепиской
        sender = await event.get_sender()
        if not isinstance(sender, User) or sender.bot:
            return
        display_name = " ".join(filter(None, [sender.first_name, sender.last_name]))
        if on_incoming_message:
            await on_incoming_message(
                tg_user_id=str(sender.id),
                username=sender.username,
                display_name=display_name,
                text=event.raw_text,
            )

    if not client.is_connected():
        await client.connect()


async def send_message_to_user(tg_user_id: str, text: str):
    """Отправляет сообщение конкретному пользователю ОТ ЛИЦА нашего аккаунта-приманки.
    Вызывается только после подтверждения оператором в дашборде."""
    await client.send_message(int(tg_user_id), text)


async def send_message_to_username(username: str, text: str):
    """Отправляет сообщение по username (используется для отчётов админу/родителям).
    username можно передавать с @ или без — Telethon сам разберётся."""
    username = username.lstrip("@")
    await client.send_message(username, text)


async def import_history(limit_per_chat: int = 200, since: datetime.datetime | None = None):
    """
    Импортирует историю уже существующих личных переписок (сообщения, которые были
    ДО подключения Qalqan к этому аккаунту). Вызывается один раз при подключении
    (или вручную из дашборда), чтобы старые диалоги с мошенниками тоже попали в анализ.

    since: если указано — импортируются только сообщения НЕ СТАРЕЕ этой даты
    (например, "не старше суток" — datetime.now(UTC) - timedelta(hours=24)).
    Telegram хранит время сообщений в UTC, поэтому since тоже должен быть в UTC.

    Возвращает список словарей с данными сообщений — обработку (сохранение в БД,
    запуск агентов) выполняет вызывающий код в main.py, используя тот же
    on_incoming_message callback, что и для новых сообщений.
    """
    if not client.is_connected():
        await client.connect()

    imported = []
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if not isinstance(entity, User) or entity.bot:
            continue  # только личные переписки с обычными пользователями

        messages = await client.get_messages(entity, limit=limit_per_chat)
        # Telethon отдаёт сообщения от новых к старым — разворачиваем в хронологический порядок
        for msg in reversed(messages):
            if not msg.message:
                continue
            if msg.out:
                continue  # пропускаем исходящие — в истории нас интересуют только входящие
            if since and msg.date < since:
                continue  # сообщение старше разрешённого периода — пропускаем
            display_name = " ".join(filter(None, [entity.first_name, entity.last_name]))
            imported.append({
                "tg_user_id": str(entity.id),
                "username": entity.username,
                "display_name": display_name,
                "text": msg.message,
                "created_at": msg.date,
            })
    return imported

