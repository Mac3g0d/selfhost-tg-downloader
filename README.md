# selfhost-tg-downloader

Telegram-бот для скачивания видео из TikTok и Instagram. Автоматически определяет ссылки в сообщениях и отправляет скачанные видео прямо в чат.

## Особенности

- Поддержка TikTok (`tiktok.com`, `vm.tiktok.com`, `vt.tiktok.com`)
- Поддержка Instagram (`instagram.com`, `instagr.am`)
- Автоматическое определение ссылок в сообщениях
- Кэширование file_id для повторных ссылок (уменьшает нагрузку и ускоряет ответы)
- Inline-режим (отправка медиа напрямую из поиска)
- Ограничение размера файлов (50 MB по умолчанию)
- Полностью самохостовый (работает на вашем сервере)

## Архитектура

Подробная документация по архитектуре доступна в [agents.md](agents.md).

## Стек технологий

| Компонент       | Технология          |
|-----------------|---------------------|
| Язык            | Python 3.14         |
| Фреймворк       | aiogram 3.x         |
| Скачивание      | gallery-dl + ffmpeg |
| Менеджер        | uv                  |
| Деплой          | systemd / Docker    |
| Логирование     | structlog           |
| Кэширование     | SQLite (aiosqlite)  |

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

### 3. Установи зависимости

```bash
uv sync --extra dev
```

### 4. Запусти бота

```bash
TELEGRAM_BOT_TOKEN=your_token uv run python -m src
```

### 5. Или через systemd (рекомендуется)

1. Создай пользователя `tg-bot`:
   ```bash
   useradd -m tg-bot
   ```

2. Скопируй код в `/opt/tg-downloader`:
   ```bash
   cp -r . /opt/tg-downloader
   chown -R tg-bot:tg-bot /opt/tg-downloader
   ```

3. Создай `/opt/tg-downloader/.env` с настройками.

4. Создай systemd сервис `/etc/systemd/system/tg-downloader.service`:
   ```ini
   [Unit]
   Description=Telegram Media Downloader Bot
   After=network.target

   [Service]
   Type=simple
   User=tg-bot
   Group=tg-bot
   WorkingDirectory=/opt/tg-downloader
   ExecStart=/opt/tg-downloader/.venv/bin/python src
   Restart=always
   RestartSec=5
   EnvironmentFile=/opt/tg-downloader/.env

   [Install]
   WantedBy=multi-user.target
   ```

5. Запусти и включи сервис:
   ```bash
   systemctl daemon-reload
   systemctl start tg-downloader
   systemctl enable tg-downloader
   ```

## Локальная разработка

```bash
# Установка зависимостей
uv sync --extra dev

# Запуск бота
TELEGRAM_BOT_TOKEN=your_token uv run python -m src

# Тесты
uv run pytest

# Линтер
uv run ruff check src/ tests/

# Тайпчекер
uv run mypy src/
```

## Конфигурация

### Переменные окружения

| Переменная           | Обязательная | По умолчанию         | Описание                                |
|----------------------|:------------:|----------------------|-----------------------------------------|
| `TELEGRAM_BOT_TOKEN` | ✅            | —                    | Токен от @BotFather                     |
| `BUFFER_CHAT_ID`     | ❌            | —                    | ID буферного канала для inline-режима   |
| `DOWNLOAD_DIR`       | ❌            | `/tmp/tg-downloads`  | Каталог для временных загрузок          |
| `DOWNLOAD_TIMEOUT`   | ❌            | `120`                | Таймаут скачивания (секунды)            |
| `GALLERY_DL_BIN`     | ❌            | `gallery-dl`         | Путь к бинарнику gallery-dl             |
| `COOKIES_FILE`       | ❌            | —                    | Путь к файлу с куками Instagram         |
| `INSTAGRAM_USER`     | ❌            | —                    | Логин Instagram (для авторизации)       |
| `INSTAGRAM_PASS`     | ❌            | —                    | Пароль Instagram                         |
| `max_telegram_file_size` | ❌        | `50 * 1024 * 1024`   | Макс. размер файла для отправки в Telegram |

## Дедупликация ссылок

Бот использует кэширование file_id для предотвращения повторных скачиваний. При получении ссылки:

1. Проверяется кэш (SQLite база `data/cache.db`)
2. Если ссылка найдена — отправляются сохранённые file_id
3. Если не найдена — ссылка скачивается и file_id сохраняются в кэш

## Безопасность

- **Запуск от непривилегированного пользователя** — обязательно используйте systemd с `User=tg-bot`
- **Ограничение размера файлов** — предотвращает заполнение диска большими файлами
- **Автоматическая очистка** — временные файлы удаляются после отправки
- **Валидация URL** — поддерживаются только TikTok и Instagram

## Мониторинг

Логи выводятся в stdout и ротируются через journalctl. Для просмотра логов:
```bash
journalctl -u tg-downloader -f
```

## Codegraph

Проект использует [codegraph](https://github.com/colbymchenry/codegraph) для генерации архитектурных диаграмм. Конфигурация находится в `.codegraph/config.yaml`. Для генерации диаграммы:
```bash
codegraph run
```
Диаграмма будет сохранена в `docs/architecture.svg`.

## Лицензия

MIT
