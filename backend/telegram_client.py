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

ВАЖНО про API_ID/API_HASH: это идентификатор ПРИЛОЖЕНИЯ Qalqan (выдаётся один раз
на my.telegram.org), а не персональный ключ каждого пользователя. Разные операторы
просто входят под своим номером телефона, используя один и тот же API_ID/API_HASH —
поэтому спрашивать это у каждого пользователя не нужно, достаточно настроить один раз.
"""
import os
import datetime
from pathlib import Path
from telethon import TelegramClient, events
from telethon.tl.types import User
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_PATH)  # всегда ищем .env рядом с этим файлом, независимо от CWD

SESSION_NAME = "qalqan_session"

# Клиент создаётся ЛЕНИВО (не при импорте модуля), чтобы приложение могло
# запуститься и показать форму настройки, даже если API_ID/API_HASH ещё не заданы.
_client: TelegramClient | None = None

# Callback, который main.py подставит при старте — вызывается на каждое новое
# входящее личное сообщение. Сигнатура: async def(tg_user_id, username, display_name, text)
on_incoming_message = None


class NotConfiguredError(Exception):
    """Telegram API_ID/API_HASH ещё не настроены."""
    pass


def app_credentials_configured() -> bool:
    api_id = os.getenv("TELEGRAM_API_ID", "").strip()
    api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()
    return bool(api_id and api_hash and api_id != "0")


def get_client() -> TelegramClient:
    """Возвращает (создавая при необходимости) единственный экземпляр TelegramClient."""
    global _client
    if _client is not None:
        return _client
    if not app_credentials_configured():
        raise NotConfiguredError(
            "TELEGRAM_API_ID/TELEGRAM_API_HASH ещё не настроены. "
            "Заполните их через форму настройки на сайте (или в .env)."
        )
    api_id = int(os.getenv("TELEGRAM_API_ID"))
    api_hash = os.getenv("TELEGRAM_API_HASH")
    _client = TelegramClient(SESSION_NAME, api_id, api_hash)
    return _client


def save_app_credentials(api_id: str, api_hash: str, phone: str = ""):
    """
    Сохраняет TELEGRAM_API_ID / TELEGRAM_API_HASH / TELEGRAM_PHONE в файл .env
    (создаёт файл из .env.example, если его ещё нет) и обновляет переменные
    окружения в текущем процессе, чтобы новые значения подхватились сразу,
    без перезапуска сервера.
    """
    global _client

    if not ENV_PATH.exists():
        example = ENV_PATH.parent / ".env.example"
        if example.exists():
            ENV_PATH.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            ENV_PATH.write_text("", encoding="utf-8")

    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    updates = {
        "TELEGRAM_API_ID": api_id.strip(),
        "TELEGRAM_API_HASH": api_hash.strip(),
    }
    if phone.strip():
        updates["TELEGRAM_PHONE"] = phone.strip()

    seen = set()
    new_lines = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else None
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            new_lines.append(line)
    for key, value in updates.items():
        if key not in seen:
            new_lines.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    # Обновляем переменные окружения текущего процесса и сбрасываем закешированный клиент,
    # чтобы новые ключи применились без перезапуска uvicorn.
    for key, value in updates.items():
        os.environ[key] = value
    _client = None


async def request_login_code(phone: str):
    """Шаг 1 авторизации: запросить код подтверждения на телефон."""
    client = get_client()
    await client.connect()
    sent = await client.send_code_request(phone)
    return sent.phone_code_hash


async def confirm_login_code(phone: str, code: str, phone_code_hash: str, password: str | None = None):
    """Шаг 2 авторизации: ввести код (и пароль 2FA, если включён)."""
    from telethon.errors import SessionPasswordNeededError
    client = get_client()
    try:
        await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
    except SessionPasswordNeededError:
        if not password:
            raise
        await client.sign_in(password=password)
    return await client.get_me()


async def is_authorized() -> bool:
    if not app_credentials_configured():
        return False
    client = get_client()
    if not client.is_connected():
        await client.connect()
    return await client.is_user_authorized()


async def start_listening():
    """Регистрирует обработчик входящих личных сообщений и запускает клиента."""
    client = get_client()

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
    client = get_client()
    await client.send_message(int(tg_user_id), text)


async def send_message_to_username(username: str, text: str):
    """Отправляет сообщение по username (используется для отчётов админу/родителям).
    username можно передавать с @ или без — Telethon сам разберётся."""
    client = get_client()
    username = username.lstrip("@")
    await client.send_message(username, text)


async def import_history(limit_per_chat: int = 200, since: datetime.datetime | None = None):
    """
    Импортирует историю уже существующих личных переписок (сообщения, которые были
    ДО подключения Qalqan к этому аккаунту). Вызывается один раз при подключении
    (или вручную из дашборда), чтобы старые диалоги с мошенниками тоже попали в анализ.

    since: если указано — импортируются только сообщения НЕ СТАРЕЕ этой даты.
    """
    client = get_client()
    if not client.is_connected():
        await client.connect()

    imported = []
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if not isinstance(entity, User) or entity.bot:
            continue  # только личные переписки с обычными пользователями

        messages = await client.get_messages(entity, limit=limit_per_chat)
        for msg in reversed(messages):
            if not msg.message:
                continue
            if msg.out:
                continue
            if since and msg.date < since:
                continue
            display_name = " ".join(filter(None, [entity.first_name, entity.last_name]))
            imported.append({
                "tg_user_id": str(entity.id),
                "username": entity.username,
                "display_name": display_name,
                "text": msg.message,
                "created_at": msg.date,
            })
    return imported
