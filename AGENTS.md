# Техническое задание на разработку Telegram-бота для репоста публикаций

## 1. Общее описание проекта

Телеграм-бот для автоматического репоста случайных публикаций из публичного канала-источника в целевой канал с отслеживанием уже опубликованных сообщений.

## 2. Технический стек

### 2.1 Язык и зависимости
- **Язык программирования**: Python 3.11 (версия фиксируется в runtime.txt)
- **Управление зависимостями**: requirements.txt с фиксированными версиями всех библиотек
- **Основные библиотеки**:
  - `telethon` — для работы с User API (чтение публичного канала)
  - `python-telegram-bot` или `aiogram` — для работы с Bot API (публикация в целевой канал)
  - `psycopg2-binary` или `asyncpg` — для работы с PostgreSQL
  - `python-dotenv` — для управления переменными окружения
  - `pytz` — для работы с часовыми поясами

### 2.2 Инфраструктура
- **Хостинг**: Render.com (Free Tier, Web Service)
- **База данных**: Render.com PostgreSQL (Free Tier)
- **CI/CD**: GitHub Actions для периодического пробуждения сервиса

## 3. Архитектура решения

### 3.1 Структура проекта
```
telegram-repost-bot/
├── .github/
│   └── workflows/
│       └── wake-up.yml          # GitHub Actions для пробуждения
├── src/
│   ├── __init__.py
│   ├── main.py                  # Точка входа
│   ├── config.py                # Конфигурация и переменные окружения
│   ├── database.py              # Работа с PostgreSQL
│   ├── user_client.py           # Telethon User API
│   ├── bot_client.py            # Bot API для репоста
│   └── scheduler.py             # Логика выбора и репоста
├── .env.example                 # Пример переменных окружения
├── .gitignore
├── requirements.txt             # Зависимости с фиксированными версиями
├── runtime.txt                  # Версия Python
└── README.md                    # Документация проекта
```

### 3.2 Схема базы данных

База данных будет содержать таблицы с префиксом `repost_` для изоляции от других проектов:

**Таблица 1: `repost_posts`**
```sql
CREATE TABLE repost_posts (
    id SERIAL PRIMARY KEY,
    message_id INTEGER UNIQUE NOT NULL,
    channel_id BIGINT NOT NULL,
    post_date TIMESTAMP NOT NULL,
    is_reposted BOOLEAN DEFAULT FALSE,
    reposted_at TIMESTAMP NULL,
    content_preview TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_repost_posts_not_reposted ON repost_posts(is_reposted, post_date);
```

**Таблица 2: `repost_session`**
```sql
CREATE TABLE repost_session (
    key VARCHAR(255) PRIMARY KEY,
    value BYTEA NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Таблица 3: `repost_config`**
```sql
CREATE TABLE repost_config (
    key VARCHAR(255) PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 4. Функциональные требования

### 4.1 Первый запуск (инициализация)
1. Подключение к User API через Telethon
2. Восстановление сессии из БД (если существует) или создание новой
3. Получение всех сообщений из канала `@pulkrug` за период **30.10.2022 — 24.10.2024**
4. Сохранение метаданных каждого сообщения в таблицу `repost_posts`
5. Сохранение session-данных Telethon в таблицу `repost_session`

### 4.2 Последующие запуски
1. Восстановление Telethon-сессии из БД
2. Проверка наличия непубликованных постов (`is_reposted = FALSE`)
3. Если непубликованных постов нет — завершение работы с логированием
4. Если есть — случайный выбор одного поста из доступных
5. Получение полного содержимого поста из канала-источника
6. Репост в целевой канал через Bot API
7. Обновление записи в БД: установка `is_reposted = TRUE`, `reposted_at = NOW()`

### 4.3 HTTP-эндпоинт для пробуждения
Бот должен поднимать минимальный веб-сервер (Flask/FastAPI) с эндпоинтом:
- `GET /health` — возвращает `{"status": "ok", "timestamp": "..."}` (200 OK)
- `POST /trigger_repost` — принудительно запускает процесс репоста

## 5. Конфигурация и переменные окружения

Файл `.env` должен содержать:

```env
# Telegram User API (для чтения канала)
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_PHONE=+79991234567

# Telegram Bot API (для публикации)
TELEGRAM_BOT_TOKEN=your_bot_token
TARGET_CHANNEL_ID=-1001234567890

# Канал-источник
SOURCE_CHANNEL=pulkrug

# Диапазон дат
START_DATE=2022-10-30
END_DATE=2024-10-24

# PostgreSQL
DATABASE_URL=postgresql://user:password@host:5432/dbname

# Веб-сервер
PORT=10000
```

## 6. GitHub Actions Workflow

Файл `.github/workflows/wake-up.yml`:

```yaml
name: Wake Up Render Service

on:
  schedule:
    # 10:00 MSK = 07:00 UTC
    - cron: '0 7 * * *'
    # 22:00 MSK = 19:00 UTC
    - cron: '0 19 * * *'
  workflow_dispatch: # Возможность ручного запуска

jobs:
  wake-up:
    runs-on: ubuntu-latest
    steps:
      - name: Send wake-up request
        run: |
          curl -X GET ${{ secrets.RENDER_SERVICE_URL }}/health
          sleep 5
          curl -X POST ${{ secrets.RENDER_SERVICE_URL }}/trigger_repost
```

**Секреты GitHub**:
- `RENDER_SERVICE_URL` — URL сервиса на Render (например, `https://your-bot.onrender.com`)

## 7. Логика работы с Telethon Session

### 7.1 Сохранение сессии в БД
```python
# Пример логики
class DatabaseSession(MemorySession):
    def __init__(self, db_connection):
        super().__init__()
        self.db = db_connection
        self._load_from_db()
    
    def _load_from_db(self):
        # Загрузка session из repost_session
        pass
    
    def save(self):
        # Сохранение session в repost_session
        super().save()
        self._save_to_db()
```

### 7.2 Обработка авторизации
При первом запуске (если сессии нет):
1. Запросить код подтверждения из Telegram
2. **Важно**: На Render нет интерактивного ввода, поэтому код нужно передавать через переменную окружения `TELEGRAM_AUTH_CODE` или через API-эндпоинт

**Рекомендуемое решение**: Авторизация должна быть выполнена локально перед деплоем, а session-данные загружены в БД вручную через миграцию или скрипт.

## 8. Обработка ошибок

### 8.1 Критические ошибки
- Нет подключения к БД → логирование, завершение с кодом 1
- Нет подключения к Telegram API → повтор через 60 секунд (до 3 попыток)
- Истекла сессия Telethon → логирование, уведомление в отдельный канал для администратора

### 8.2 Некритические ошибки
- Пост не найден в канале-источнике → пропуск, пометка в БД
- Ошибка репоста в целевой канал → повтор через 30 секунд (до 3 попыток)

## 9. Логирование

- Использовать стандартный модуль `logging`
- Уровни: INFO для обычных операций, WARNING для проблем, ERROR для критических ошибок
- Формат логов: `[TIMESTAMP] [LEVEL] [MODULE] Message`
- Логирование в stdout (Render перехватывает автоматически)

## 10. Дополнительные требования

### 10.1 Особенности репоста
- Сохранять форматирование оригинального поста
- Копировать медиафайлы (фото, видео, документы)
- Опционально: добавлять подпись с ссылкой на оригинал

### 10.2 Производительность
- Первая инициализация может занять несколько минут (получение всех постов за 2 года)
- Обычный запуск должен выполняться за 5-15 секунд
- Веб-сервер должен отвечать на `/health` за < 2 секунды

### 10.3 Безопасность
- Все секретные данные только через переменные окружения
- `.env` файл добавлен в `.gitignore`
- Session-данные зашифрованы в БД (опционально)

## 11. План деплоя

1. Создать PostgreSQL базу на Render
2. Выполнить миграции (создание таблиц)
3. **Локально**: авторизоваться через Telethon и сохранить session в БД
4. Создать Web Service на Render
5. Настроить переменные окружения на Render
6. Добавить секреты в GitHub
7. Активировать GitHub Actions workflow
8. Провести тестовый запуск

## 12. Критерии приемки

- [ ] Бот успешно инициализируется и загружает все посты из канала за указанный период
- [ ] Сессия Telethon сохраняется и восстанавливается из PostgreSQL
- [ ] Бот корректно выбирает случайный непубликованный пост
- [ ] Репост выполняется с сохранением форматирования и медиа
- [ ] После репоста пост помечается как опубликованный в БД
- [ ] Повторные репосты исключены
- [ ] Веб-сервер отвечает на `/health` и `/trigger_repost`
- [ ] GitHub Actions успешно пробуждает сервис по расписанию
- [ ] Логи содержат достаточно информации для отладки
- [ ] Все зависимости зафиксированы в requirements.txt

## 13. Тестирование и Quality Assurance

### 13.1 Покрытие тестами
- Минимальное покрытие кода тестами: **70%**
- Обязательное покрытие критических модулей:
  - `database.py` — 80%+
  - `user_client.py` — 70%+
  - `bot_client.py` — 70%+
  - `scheduler.py` — 80%+

### 13.2 Типы тестов

**Unit-тесты**:
- Тестирование функций работы с БД (создание, чтение, обновление записей)
- Тестирование логики выбора случайного поста
- Тестирование парсинга конфигурации и переменных окружения
- Использовать `pytest` с фикстурами для mock-объектов

**Интеграционные тесты**:
- Тестирование записи/чтения session из PostgreSQL
- Тестирование веб-эндпоинтов `/health` и `/trigger_repost`
- Использовать тестовую БД (SQLite in-memory или отдельный PostgreSQL для CI)

**Структура тестов**:
```
tests/
├── __init__.py
├── conftest.py              # Общие фикстуры
├── test_database.py
├── test_user_client.py
├── test_bot_client.py
├── test_scheduler.py
└── test_api_endpoints.py
```

### 13.3 Continuous Integration
Добавить в `.github/workflows/tests.yml`:
```yaml
name: Run Tests

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-cov pytest-asyncio
      - name: Run tests with coverage
        run: |
          pytest tests/ --cov=src --cov-report=xml --cov-report=term
      - name: Check coverage threshold
        run: |
          coverage report --fail-under=70
```

### 13.4 Логирование для отладки

**Структурированное логирование**:
- Использовать библиотеку `structlog` или стандартный `logging` с JSON-форматтером
- Каждая запись должна содержать:
  - Timestamp (ISO 8601 с таймзоной)
  - Уровень (DEBUG, INFO, WARNING, ERROR, CRITICAL)
  - Модуль/функция
  - Message
  - Контекст (например, `message_id`, `channel_id`)

**Пример формата лога**:
```json
{
  "timestamp": "2024-12-05T10:00:00+03:00",
  "level": "INFO",
  "module": "scheduler",
  "function": "select_random_post",
  "message": "Selected post for repost",
  "context": {
    "message_id": 12345,
    "post_date": "2023-05-15",
    "available_posts": 487
  }
}
```

**Уровни логирования по модулям**:
- `main.py` — INFO: запуск/остановка приложения
- `database.py` — DEBUG: все SQL-запросы, INFO: подключение/отключение
- `user_client.py` — INFO: подключение к Telegram, WARNING: проблемы с сессией
- `bot_client.py` — INFO: успешные репосты, ERROR: ошибки публикации
- `scheduler.py` — INFO: выбор поста, статистика доступных постов

**Ротация и хранение логов на Render**:
- Render автоматически захватывает stdout/stderr
- Логи доступны через дашборд Render (последние 7 дней на Free Tier)
- Для долгосрочного хранения: опционально настроить отправку критических логов в Telegram-канал администратора

### 13.5 Мониторинг и алерты

**Health-check расширенный**:
```python
GET /health
Response:
{
  "status": "healthy",
  "timestamp": "2024-12-05T10:00:00Z",
  "database": "connected",
  "telegram_user_api": "connected",
  "telegram_bot_api": "connected",
  "unpublished_posts": 487,
  "last_repost": "2024-12-05T09:30:00Z"
}
```

**Критерии для алертов**:
- База данных недоступна более 5 минут
- Ошибки Telegram API более 3 раз подряд
- Не осталось непубликованных постов
- Сессия Telethon истекла

### 13.6 Документация тестов

В `README.md` добавить секцию:
```markdown
## Запуск тестов

### Локально
```bash
# Установка зависимостей для разработки
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Запуск всех тестов
pytest tests/

# Запуск с покрытием
pytest tests/ --cov=src --cov-report=html

# Запуск конкретного теста
pytest tests/test_database.py::test_save_post
```

### В Docker (опционально)
```bash
docker-compose -f docker-compose.test.yml up --abort-on-container-exit
```
```

### 13.7 Критерии качества кода

- **Линтеры**: использовать `flake8` или `ruff` для проверки стиля кода (PEP 8)
- **Форматирование**: `black` для автоформатирования
- **Типизация**: использовать type hints, проверка через `mypy` (опционально)
- **Pre-commit hooks**: настроить `.pre-commit-config.yaml` для автоматических проверок перед коммитом

**Файл `requirements-dev.txt`**:
```
pytest==7.4.3
pytest-cov==4.1.0
pytest-asyncio==0.21.1
black==23.11.0
flake8==6.1.0
mypy==1.7.1
```

### 13.8 Acceptance-тесты

**Чек-лист ручного тестирования перед продакшеном**:
- [ ] Первый запуск: все посты загружены в БД
- [ ] Повторный запуск: выбирается случайный непубликованный пост
- [ ] Репост содержит весь контент оригинала (текст, медиа, форматирование)
- [ ] После репоста пост помечен в БД как опубликованный
- [ ] `/health` возвращает 200 OK с корректными данными
- [ ] `/trigger_repost` запускает репост и возвращает результат
- [ ] GitHub Actions успешно пробуждает сервис
- [ ] Логи содержат достаточно информации для диагностики
- [ ] При истечении сессии Telethon логируется понятная ошибка
- [ ] При отсутствии непубликованных постов бот корректно завершается

---

## Примечания

Это техническое задание описывает минимально работающую версию бота. В будущем можно добавить:
- Веб-панель администратора для управления ботом
- Статистику репостов
- Возможность настройки интервалов репоста через БД
- Поддержку нескольких каналов-источников