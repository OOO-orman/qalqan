# Qalqan — ИИ-система защиты от мошенников

Мультиагентная система: honeypot-переписка (human-in-the-loop) → извлечение данных →
определение схемы мошенничества → поиск связей между делами → генерация отчёта.

## Архитектура

```
Мошенник → Telegram (ваш аккаунт-приманка)
              │
              ▼
      Intelligence Agent (извлечение: телефоны, карты, telegram, ссылки, крипто, email)
              │
              ▼
      Scam Detection Agent (тип схемы, уровень риска 0-10, признаки)
              │
              ▼
      Response Agent (черновик ответа персонажа)  ──► Оператор в дашборде решает:
              │                                          отправить / отредактировать / пропустить
              ▼
      Link Analysis Agent (совпадения с другими делами)
              │
              ▼
      Report Agent (итоговый отчёт для банка/МВД)
```

**Важно:** система не пишет мошенникам первой и не отправляет ничего без подтверждения
оператора. Она реагирует на входящие сообщения в вашем Telegram-аккаунте и предлагает
черновик ответа — вы решаете, отправлять его, отредактировать или пропустить.

## Установка

### 1. Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Настройка ключей

```bash
cp .env.example .env
```

Откройте `.env` и заполните:

- **GEMINI_API_KEY** — получить на https://aistudio.google.com → "Get API key" (бесплатно, без карты)
- **TELEGRAM_API_ID** и **TELEGRAM_API_HASH** — получить на https://my.telegram.org →
  "API development tools" (см. инструкцию ниже)
- **TELEGRAM_PHONE** — номер аккаунта-приманки в формате +7XXXXXXXXXX

### 3. Запуск backend

```bash
cd backend
uvicorn main:app --reload --port 8000
```

При первом запуске в браузере откройте дашборд (см. ниже) — появится экран входа в
Telegram: введите номер телефона, затем код из Telegram (придёт в само приложение
Telegram на этот номер), при необходимости — пароль двухфакторной аутентификации.

### 4. Запуск дашборда

Просто откройте файл `frontend/index.html` в браузере (двойной клик, либо через
`python3 -m http.server` из папки `frontend`, если браузер блокирует локальные файлы).

Если backend работает на другом порту/хосте — поправьте константу `API_BASE`
в начале `<script>` в `index.html`.

## Как получить API_ID и API_HASH для Telegram

1. Зайдите на my.telegram.org, войдите под своим номером (придёт код в Telegram)
2. Нажмите "API development tools"
3. Заполните форму (App title/Short name — любые значения)
4. Нажмите "Create application" — получите `api_id` и `api_hash`

## Как получить ключ Gemini

1. Зайдите на aistudio.google.com
2. Войдите через Google-аккаунт
3. "Get API key" → "Create API key"

Бесплатный тариф не требует карты, но имеет лимиты запросов в минуту/день —
для демо и тестов этого достаточно с запасом.

## Структура проекта

```
qalqan/
├── backend/
│   ├── main.py                  — FastAPI-приложение, REST + WebSocket, оркестрация
│   ├── database.py              — модели SQLAlchemy (Conversation, Message, Entity, Report)
│   ├── gemini_client.py         — обёртка над Gemini API
│   ├── telegram_client.py       — интеграция с Telegram (Telethon)
│   ├── agents/
│   │   ├── extractor.py         — Intelligence Agent (извлечение данных)
│   │   ├── scam_detector.py     — Scam Detection Agent
│   │   ├── response_agent.py    — Response Agent (черновики ответов)
│   │   ├── link_analysis.py     — Link Analysis Agent
│   │   └── report_generator.py  — Report Agent
│   ├── requirements.txt
│   └── .env.example
└── frontend/
    └── index.html               — дашборд (без сборки, открывается напрямую)
```

## Важные замечания по безопасности и этике

- **Не публикуйте `.env` файл** (там ключи API и телефон) — добавьте его в `.gitignore`
  перед загрузкой в GitHub/GitLab для сдачи проекта.
- **Ключ Gemini, который был показан в чате при разработке, стоит перевыпустить**
  (зайти в aistudio.google.com → удалить старый ключ → создать новый) — считайте его
  скомпрометированным, так как он попал в переписку.
- Everyone-in-the-loop: реальная отправка сообщений мошеннику всегда требует
  подтверждения оператора через дашборд — это защищает и от случайных ошибок ИИ,
  и от этических/юридических рисков автономного контакта с реальными людьми.
- Данные (номера карт, телефоны и т.д.), которые собирает система, — чувствительная
  информация. Ограничьте доступ к базе данных (`qalqan.db`) и передавайте отчёты
  только по официальным защищённым каналам связи с банком/МВД.
