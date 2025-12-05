# Telegram Repost Bot

Бот для репоста случайных публикаций из публичного канала в целевой канал. Веб-сервер реализован на FastAPI с эндпоинтами `/health` и `/trigger_repost`, вся логика репоста вынесена в `src/`.

## Стек
- Python 3.11 (фиксируется в `runtime.txt`)
- Telethon для User API
- python-telegram-bot для Bot API
- asyncpg + Supabase (PostgreSQL)
- FastAPI + uvicorn
- pytest для тестов
- structlog для структурированных логов

## Структура проекта
```
telegram-repost-bot/
├── .github/workflows
│   ├── tests.yml
│   └── wake-up.yml
├── src/
│   ├── __init__.py
│   ├── bot_client.py
│   ├── config.py
│   ├── database.py
│   ├── main.py
│   ├── scheduler.py
│   └── user_client.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_api_endpoints.py
│   ├── test_bot_client.py
│   ├── test_config.py
│   ├── test_database.py
│   ├── test_scheduler.py
│   └── test_user_client.py
├── .env.example
├── .gitignore
├── requirements.txt
├── requirements-dev.txt
├── runtime.txt
└── README.md
```

## Настройка окружения
1. Создайте виртуальное окружение и установите зависимости:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   pip install -r requirements-dev.txt  # для разработки и тестов
   ```
2. Скопируйте `.env.example` в `.env` и заполните переменные:
   - Телеграм User API: `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE`, `TELEGRAM_AUTH_CODE`
   - Телеграм Bot API: `TELEGRAM_BOT_TOKEN`, `TARGET_CHANNEL_ID`
   - Канал-источник: `SOURCE_CHANNEL`
   - Диапазон дат: `START_DATE=2022-10-30`, `END_DATE=2024-10-24`, `TIMEZONE=UTC`
   - Supabase: `DATABASE_URL` (Connection string → URI), `SUPABASE_URL`, `SUPABASE_ANON_KEY` (или service key, если включен RLS)
   - Веб-сервер: `PORT`, `LOG_LEVEL`

### Supabase вместо Render Postgres
- В Supabase зайдите в `Project Settings → Database → Connection string → URI` и возьмите DSN в формате `postgresql://...supabase.co:5432/postgres` — это значение ставим в `DATABASE_URL`.
- Там же в `Project API` возьмите `SUPABASE_URL` и `anon` или `service_role` key и пропишите как `SUPABASE_ANON_KEY` (ключ нужен для будущих интеграций/health).
- База в Supabase не обнуляется, таблицы `repost_*` создаются приложением при старте.

## Первый запуск и инициализация
1. Убедитесь, что Supabase Postgres доступен и пустой (подключение по `DATABASE_URL` из Supabase).
2. Выполните локально (до деплоя) для получения session Telethon и загрузки постов:
   ```bash
   python -m src.main
   ```
   Приложение поднимет веб-сервер и при старте:
   - создаст таблицы `repost_*` в базе;
   - авторизуется в Telethon, используя `TELEGRAM_AUTH_CODE` (предварительно получите код в Telegram);
   - **если таблица постов пуста** — загрузит метаданные постов из канала за указанный период в `repost_posts`;
   - сохранит session в таблицу `repost_session`.
3. После первой синхронизации задеплойте сервис на Render и установите переменные окружения.

## Запуск сервера локально
```bash
uvicorn src.main:app --host 0.0.0.0 --port $PORT
```
Эндпоинты:
- `GET /health` — статус приложения и метрики.
- `POST /trigger_repost` — принудительный запуск репоста одного поста.
Пример `/health`:
```json
{
  "status": "ok",
  "timestamp": "2024-01-01T00:00:00Z",
  "database": "connected",
  "telegram_user_api": "connected",
  "telegram_bot_api": "connected",
  "unpublished_posts": 123,
  "last_repost": "2024-01-01T00:00:00"
}
```

## Тесты
```bash
pytest tests/ --cov=src --cov-report=term
```
Минимальный порог покрытия — 70% (также проверяется в CI).

## Линтинг и pre-commit
- Линтеры: `flake8`, форматирование: `black`, типы: `mypy`.
- Pre-commit: `pre-commit install` (конфиг в `.pre-commit-config.yaml`).
- Ручной запуск:
  ```bash
  black src tests
  flake8 src tests
  mypy src
  ```

## Docker
Локальный запуск в контейнере (пример):
```bash
cat > Dockerfile <<'EOF'
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "10000"]
EOF

docker build -t telegram-repost-bot .
docker run -p 10000:10000 --env-file .env telegram-repost-bot
```

## CI/CD
- `.github/workflows/tests.yml` — запускает тесты на push/PR.
- `.github/workflows/wake-up.yml` — два раза в день (07:00 и 19:00 UTC) дергает эндпоинты Render для пробуждения.

## Примечания по логированию
- Логи структурированы в JSON через `structlog` (timestamp, level, logger, message и контекст: `message_id`, `channel_id`, и т.д.).
- Покрывают подключение к БД, авторизацию в Telegram, выбор и репост постов.

## Дальнейшие шаги
- Добавить оповещения о критических ошибках в личные сообщения указанному контактному лицу.
- Расширить health-check дополнительными проверками (подключение к Telegram Bot/User API).
- Настроить pre-commit с black/flake8/mypy.
