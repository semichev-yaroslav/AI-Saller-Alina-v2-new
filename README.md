# AI Saller Alina

Демонстрационная backend-версия AI-менеджера продаж для Telegram.

`AI Saller Alina` обрабатывает входящие сообщения клиентов, определяет `intent`, стадию лида, генерирует ответ через LLM и сохраняет историю диалога. Проект показывает подход к построению AI-сервиса с Telegram-интеграцией, API, базой данных и отдельным AI-слоем.

## Обзор

Сценарий приложения:

- пользователь пишет боту в Telegram;
- сообщение сохраняется в базе данных;
- AI-модуль получает текущее сообщение, историю диалога и каталог услуг;
- система определяет `intent`, стадию лида и формирует ответ;
- ответ сохраняется и отправляется пользователю.

## Ключевые возможности

- Обработка входящих сообщений из Telegram (long polling) и через demo endpoint.
- Сохранение полной истории переписки и AI-вызовов.
- AI-анализ сообщения с учетом истории диалога и каталога услуг.
- В AI-контекст передаются последние 100 сообщений конкретного пользователя.
- Подключаемая база знаний компании из файлов (`knowledge/company/*.md|*.txt`).
- Структурированный AI-ответ: `intent`, `stage`, `reply_text`, `confidence`.
- Каталог услуг с демо-данными и стартовыми ценами.
- Follow-up цепочка возврата клиента: `+2ч`, `+24ч`, `+72ч` в окне 11:00-20:00 (МСК).
- Бронирование консультации через запрос удобных даты и времени у клиента.
- Обработка stop-фраз с паузой диалога и повторной активацией при новом сообщении клиента.
- Уведомления админа в Telegram о записи на консультацию и запросах на живого менеджера.
- API для просмотра лидов, сообщений и услуг.
- Логи по входящим сообщениям, AI-вызовам, ошибкам и исходящим ответам.
- Отдельный стартовый сценарий `/start` для рекламного входа в воронку.

## Стек

- Python 3.11+
- FastAPI
- SQLAlchemy 2.0
- PostgreSQL
- Alembic
- OpenAI API
- Telegram Bot API
- Docker / Docker Compose
- pytest

## Архитектура

Основные слои:

- `API` — HTTP endpoints.
- `Services` — orchestration бизнес-логики и сценариев обработки.
- `Repositories` — доступ к данным через SQLAlchemy.
- `AI module` — построение prompt, вызов OpenAI, валидация результата.
- `Integrations` — Telegram API client.
- `Workers` — long polling loop для Telegram.

### Поток обработки

1. Пользователь отправляет сообщение в Telegram.
2. Worker получает update.
3. Входящее сообщение сохраняется в `messages`.
4. AI получает контекст (история + каталог услуг), возвращает structured response.
5. Результат AI сохраняется в `ai_runs`.
6. Ответ сохраняется в `messages` и отправляется в Telegram.
7. Стадия и intent лида обновляются в `leads`.

## Стартовый сценарий

Для команды `/start` используется отдельный сценарий:

- кратко объясняет назначение AI-менеджера продаж;
- перечисляет основные возможности;
- задает квалифицирующие вопросы для дальнейшего диалога.

Для новых лидов без команды `/start` используется стандартное onboarding-вступление.

## Структура проекта

```text
ai-sales-manager/
  app/
    api/
    ai/
    core/
    db/
    integrations/
    repositories/
    schemas/
    services/
    workers/
  alembic/
    versions/
  tests/
  Dockerfile
  docker-compose.yml
  .env.example
  alembic.ini
  pyproject.toml
```

## Модель данных

### `leads`

- Telegram-идентификаторы пользователя/чата
- профиль лида (`username`, `full_name`, `phone`, `email`)
- текущая стадия (`new`, `engaged`, `qualified`, `interested`, `booking_pending`, `booked`, `lost`)
- последний intent
- `qualification_data` (собранные данные по квалификации)
- `follow_up_step`, `next_follow_up_at`, `do_not_contact`, `stopped_at`
- `booking_slot_at`, `handoff_requested`

### `messages`

- входящие/исходящие сообщения
- source (`user`, `assistant`, `system`)
- channel (`telegram`, `api_simulation`)
- delivery status (`pending`, `sent`, `failed`)
- Telegram metadata (`telegram_message_id`, `telegram_update_id`)

### `services`

- каталог услуг
- описание
- `price_from`, `currency`

### `ai_runs`

- лог AI вызова
- определенный intent/stage/confidence
- текст ответа
- raw response
- статус (`success`, `error`)

## Доменные статусы

### Intent

- `greeting`
- `service_question`
- `price_question`
- `objection`
- `ready_to_buy`
- `booking_intent`
- `contact_sharing`
- `unclear`

### Lead stages

- `new`
- `engaged`
- `qualified`
- `interested`
- `booking_pending`
- `booked`
- `lost`

## API

### Обязательные endpoints

- `GET /health`
- `GET /leads`
- `GET /leads/{id}`
- `GET /leads/{id}/messages`
- `POST /simulate/message`
- `GET /services`

### Примеры

```bash
curl http://localhost:8000/health
```

```bash
curl "http://localhost:8000/leads?stage=interested&search=ivan"
```

```bash
curl -X POST http://localhost:8000/simulate/message \
  -H 'Content-Type: application/json' \
  -d '{
    "telegram_user_id": 12345,
    "telegram_chat_id": 12345,
    "username": "ivan",
    "full_name": "Ivan Petrov",
    "text": "Здравствуйте, хочу узнать цену AI-бота"
  }'
```

## Конфигурация

Скопируйте `.env.example` в `.env` и заполните секреты:

- `OPENAI_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ADMIN_CHAT_ID`
- `DATABASE_URL`

Дополнительные параметры контекста:

- `HISTORY_WINDOW_MESSAGES=100`
- `COMPANY_KNOWLEDGE_DIR=knowledge/company`
- `COMPANY_KNOWLEDGE_MAX_FILES=12`
- `COMPANY_KNOWLEDGE_MAX_CHARS=4000`

## Запуск через Docker

```bash
cp .env.example .env
# заполните OPENAI_API_KEY и TELEGRAM_BOT_TOKEN

docker compose up --build
```

После старта:

- API: `http://localhost:8000`
- Swagger: `http://localhost:8000/docs`

## Локальный запуск без Docker

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
cp .env.example .env

alembic upgrade head
uvicorn app.main:app --reload
```

Telegram worker в отдельном процессе:

```bash
python -m app.workers.telegram_polling
```

## Тесты

```bash
pytest
```

Покрыто:

- unit tests (AI logic + message processor)
- unit tests по follow-up/booking/stop/reactivation
- API tests (`/simulate/message`, `/leads`, `/leads/{id}`, `/leads/{id}/messages`)

## Примечания

- Идемпотентность Telegram update: уникальный индекс на `telegram_update_id`.
- Контакты (phone/email) извлекаются из текста и сохраняются в `leads`.
- При низкой уверенности и сложных возражениях бот предлагает подключение менеджера.
- Если `OPENAI_API_KEY` не задан, используется fallback heuristic analyzer для локального демо.
