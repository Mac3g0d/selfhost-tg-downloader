# selfhost-tg-downloader

Telegram-бот для скачивания видео из TikTok и Instagram. Автоматически определяет ссылки в сообщениях и отправляет скачанные видео прямо в чат.

## Стек

| Компонент       | Технология          |
|-----------------|---------------------|
| Язык            | Python 3.14         |
| Фреймворк       | aiogram 3.x         |
| Скачивание      | gallery-dl + ffmpeg |
| Менеджер        | uv                  |
| Деплой          | Docker + Compose    |

## Быстрый старт

### 1. Клонируй репозиторий

```bash
git clone https://github.com/Mac3g0d/selfhost-tg-downloader.git
cd selfhost-tg-downloader
```

### 2. Создай `.env`

```bash
cp .env.example .env
# Отредактируй .env — вставь свой TELEGRAM_BOT_TOKEN
```

### 3. Запусти через Docker Compose

```bash
docker compose up -d --build
```

Бот запустится, начнёт слушать сообщения и скачивать видео по ссылкам на TikTok / Instagram.

### Логи

```bash
docker compose logs -f bot
```

## Локальная разработка

```bash
# Установи зависимости
uv sync

# Запусти бота
TELEGRAM_BOT_TOKEN=your_token uv run python -m src

# Тесты
uv run pytest

# Линтер
uv run ruff check src/ tests/

# Тайпчекер
uv run mypy src/
```

## Структура проекта

```
.
├── src/
│   ├── __init__.py
│   ├── __main__.py          # Entry point
│   ├── bot.py               # Bot & Dispatcher factory
│   ├── config.py            # Environment settings
│   ├── downloader/
│   │   ├── __init__.py
│   │   └── gallery.py       # Async gallery-dl wrapper
│   └── handlers/
│       ├── __init__.py
│       └── media.py         # URL detection & message handlers
├── tests/
│   ├── __init__.py
│   ├── test_downloader.py
│   └── test_url_detection.py
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── .dockerignore
```

## Переменные окружения

| Переменная           | Обязательная | По умолчанию         | Описание                                |
|----------------------|:------------:|----------------------|-----------------------------------------|
| `TELEGRAM_BOT_TOKEN` | ✅            | —                    | Токен от @BotFather                     |
| `DOWNLOAD_DIR`       | ❌            | `/tmp/tg-downloads`  | Каталог для временных загрузок          |
| `DOWNLOAD_TIMEOUT`   | ❌            | `120`                | Таймаут скачивания (секунды)            |
| `GALLERY_DL_BIN`     | ❌            | `gallery-dl`         | Путь к бинарнику gallery-dl             |

## Лицензия

MIT