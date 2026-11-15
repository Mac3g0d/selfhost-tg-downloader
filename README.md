# selfhost-tg-downloader

[![CI](https://github.com/Mac3g0d/selfhost-tg-downloader/actions/workflows/ci.yml/badge.svg)](https://github.com/Mac3g0d/selfhost-tg-downloader/actions/workflows/ci.yml)
[![uv](https://img.shields.io/badge/dependencies-uv-DE5FE9)](https://docs.astral.sh/uv/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.14+](https://img.shields.io/badge/Python-3.14%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![aiogram 3](https://img.shields.io/badge/aiogram-3-26A5E4?logo=telegram&logoColor=white)](https://docs.aiogram.dev/)

A self-hosted Telegram bot that turns TikTok and Instagram links into videos and photos in your chat. Downloads run on your server through **gallery-dl**; a SQLite cache reuses Telegram file IDs for links the bot has already processed.

## Features

- Detect supported links in text messages and reply with the downloaded media.
- Handle TikTok links, including `vm.tiktok.com` and `vt.tiktok.com`, plus Instagram and `instagr.am` links.
- Return videos and photos, including multiple files from a single link.
- Share media through Telegram inline mode, with a separate buffer chat for uploads.
- Reuse cached media across ordinary messages and inline queries.
- Configure download timeouts, Instagram authentication, and optional aria2 downloading.
- Run locally or build a Docker image for a self-hosted deployment.

The bot uses long polling: it needs outbound internet access, not a public webhook endpoint. Bot replies and inline result titles are currently in Russian; this README is in English.

## Technology

| Component | Technology |
| --- | --- |
| Runtime | Python 3.14+ |
| Telegram API | aiogram 3 |
| Media extraction | gallery-dl; FFmpeg for media processing |
| Cache | SQLite via aiosqlite |
| Configuration | pydantic-settings and `.env` |
| Logging | structlog to standard output |
| Dependency management | uv and `uv.lock` |
| Containers | Docker and Docker Compose |

## Quickstart

### Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/) and Python 3.14.
- FFmpeg installed and available on `PATH`.
- A Telegram bot token from [@BotFather](https://t.me/BotFather).
- Network access to Telegram and the source sites.

```bash
git clone https://github.com/Mac3g0d/selfhost-tg-downloader.git
cd selfhost-tg-downloader
cp .env.example .env
```

Edit `.env` and replace `TELEGRAM_BOT_TOKEN` with your own token. Do not use the example token or commit your credentials.

```bash
uv python install 3.14
uv sync --frozen --python 3.14
uv run --frozen bot
```

Run commands from the repository root so relative configuration and data paths resolve correctly. Hatch installs the modules under `src/` as top-level modules. Use `uv run --frozen bot` or `uv run --frozen python -m tg_downloader`; no `PYTHONPATH` override is needed after installation. For an uninstalled checkout, use `PYTHONPATH=src python -m tg_downloader` (`PYTHON_ROOT` is not a Python search-path variable).

Open a private conversation with your bot, send `/start`, then send a supported TikTok or Instagram URL. For groups, configure the bot's permissions and BotFather privacy settings so it receives the messages you want it to process. Only text messages are scanned; media captions are not scanned.

Instagram downloads may require authentication; see [Instagram authentication](#instagram-authentication).

## Configuration

Settings are loaded from `.env` in the working directory and from environment variables; environment variables take precedence. Environment variable names are case-insensitive.

| Variable | Default | Purpose |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | Required | Bot token issued by BotFather. |
| `BUFFER_CHAT_ID` | `0` | Buffer chat/channel ID for inline uploads. `0` disables inline delivery. |
| `DATABASE_PATH` | `data/cache.db` | SQLite cache location; parent directories are created on startup. |
| `DOWNLOAD_DIR` | `~/.cache/tg-downloads` | Download workspaces; the sample `.env` uses `/tmp/tg-downloads`, and Docker/Compose use `/app/downloads`. |
| `DOWNLOAD_TIMEOUT` | `120` | Time limit, in seconds, for the gallery-dl subprocess. |
| `GALLERY_DL_BIN` | `gallery-dl` | gallery-dl executable name or path. |
| `COOKIES_FILE` | `cookies/instagram.txt` | Path to a Netscape-format cookies file, used only if the file exists. |
| `INSTAGRAM_USER` | Empty | Optional Instagram username; requires `INSTAGRAM_PASS`. |
| `INSTAGRAM_PASS` | Empty | Optional Instagram password; requires `INSTAGRAM_USER`. |
| `MAX_TELEGRAM_FILE_SIZE` | `52428800` bytes (50 MiB) | Per-file upload threshold in the ordinary message handler. |
| `USE_ARIA2` | `false` | Ask gallery-dl to use aria2; requires `aria2c` on `PATH`. |
| `CONCURRENT_FRAGMENTS` | `5` | Value passed to gallery-dl as `ytdl.concurrent-fragments`. |

The file-size setting is checked **after downloading**, not before. It is not a disk quota, does not raise Telegram's API limits, and is not currently applied by the inline handler. Actual download behavior depends on gallery-dl and its selected extractor/downloader.

### Instagram authentication

Export cookies for an account signed in to Instagram in Netscape `cookies.txt` format, then save them as `cookies/instagram.txt` or set `COOKIES_FILE` to another readable file path. Cookies can expire and need to be refreshed.

Alternatively, set both `INSTAGRAM_USER` and `INSTAGRAM_PASS`. When both are present, the downloader writes a temporary gallery-dl configuration and uses those credentials **instead of** the cookies file. Login challenges and site restrictions can still prevent downloads.

`COOKIES_FILE` must name a real file: setting it to a browser name such as `chrome` does not enable browser cookie extraction in this bot.

Treat cookies, tokens, passwords, and temporary authentication files as secrets. Ensure only the bot's operating-system account can read them.

## Inline mode

1. Enable inline mode for your bot with BotFather's `/setinline` command.
2. Create a private buffer channel or chat and give the bot permission to send videos and photos there. For a channel, add the bot as an administrator with posting permission.
3. Set its numeric ID in `.env`, for example `BUFFER_CHAT_ID=-1001234567890`.
4. Restart the bot, then type `@your_bot_username <supported URL>` in a Telegram chat and select a result.

On a cache miss, the bot downloads the media and uploads it to the buffer chat to obtain reusable Telegram file IDs. Each media item is a separate inline result, not an automatically sent album. A configured buffer chat is required even when the requested URL is already cached.

**Buffer chat privacy:** uploads include a caption containing the requesting user's name, Telegram ID, username when available, chat type when available, and source URL. Keep this chat private. Buffer messages are not automatically removed.

A first-time download must finish before Telegram accepts the inline response; slow downloads can exceed Telegram's inline query deadline. Repeating the query after the media has been cached may help. Successful inline responses use a 300-second Telegram result cache; empty/error responses use 5 seconds. These are separate from the persistent SQLite cache.

## Docker

Install Docker Engine with the Compose plugin, create `.env` as above, and place any required cookies in `cookies/` before starting:

```bash
docker compose up -d --build
docker compose logs -f bot
```

The Compose service is named `bot`. It reads `.env`, mounts `cookies/` read-only at `/app/cookies`, and sets `COOKIES_FILE=/app/cookies/instagram.txt` and `DOWNLOAD_DIR=/app/downloads`. These Compose environment entries override the values in `.env`.

Named volumes persist downloads at `/app/downloads` and the SQLite cache at `/app/data` (default `DATABASE_PATH=data/cache.db` under `/app`). Compose rotates Docker's `json-file` logs at 10 MB per file and retains three files. The runtime runs as UID/GID `1000:1000`; any replacement bind mounts must have compatible read/write permissions. Back up the cache if you want to retain mappings. Cookies stay in the separate read-only mount, never in the image.

For a standalone source build:

```bash
docker build --target runtime -t selfhost-tg-downloader:local .
```

## Cache behavior and limitations

- The database stores URL-to-Telegram-file-ID mappings, not copies of the downloaded media. Ordinary messages and inline mode share it.
- URL cleanup strips query strings, fragments, and trailing slashes. It does not resolve short links or merge different hostnames into one canonical key.
- Cache entries have no automatic expiry, size limit, or stale-file-ID recovery. A failed cached Telegram send does not automatically trigger a fresh download.
- The cache is keyed by URL, not by user or content hash. Simultaneous misses for the same link can still start separate downloads.
- Only successfully uploaded items are cached. If an item is skipped or an upload fails, a cached link may represent only part of the original post.
- Temporary workspaces are cleaned up by the download/send paths, but process crashes or forced shutdowns can leave files behind. Monitor free disk space.

Support is limited to the URL patterns accepted by the bot, even though gallery-dl supports other sites. Private content, expired links, login requirements, rate limits, and extractor changes can cause failures. There is no user allowlist or per-user quota in the current bot; restrict who can access your deployment if necessary.

## Local development and checks

The development dependencies are a uv dependency group, not a package extra:

```bash
uv sync --frozen --group dev --python 3.14
uv run --frozen pytest -q -o tmp_path_retention_policy=all
uv run --frozen mypy src tests
uv run --frozen ruff check src tests
uv run --frozen ruff format --check src tests
uv run --frozen ty check src tests
uv run --frozen bandit -r src
```

For the containerized toolchain, build the CI target:

```bash
docker build --target ci -t selfhost-tg-downloader:ci .
docker run selfhost-tg-downloader:ci pytest -q -o tmp_path_retention_policy=all
docker run -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0=/repo -v "$PWD:/repo:ro" selfhost-tg-downloader:ci gitleaks git /repo --log-opts="--all" --redact
docker save selfhost-tg-downloader:local -o runtime.tar
docker run -v "$PWD:/images:ro" selfhost-tg-downloader:ci trivy image --input /images/runtime.tar --scanners vuln --severity HIGH,CRITICAL --exit-code 1
```

These commands are checks to run, not a promise that every security gate is currently green. Tests isolate settings and mock destructive cleanup. Use isolated data, never production state.

### Project layout

```text
src/
  __main__.py        Source-tree script wrapper
  tg_downloader.py   Startup, logging, database initialization, polling
  config.py          Environment-based settings
  bot.py             Bot and dispatcher construction
  healthcheck.py     Startup diagnostics
  database.py        SQLite file-ID cache
  utils.py           URL cleanup
  handlers/          Commands, ordinary messages, inline queries
  downloader/        gallery-dl subprocess and media collection
tests/              Automated tests
```

Startup diagnostics report configuration paths, authentication availability, and executable discovery. They are logs, not an HTTP health endpoint or a guarantee that an external download will succeed.

## CI and releases

[CI and release](.github/workflows/ci.yml) runs on GitHub-hosted Ubuntu runners for every PR opening, new commit, and reopening, and for pushes to `main`. There are no path filters, and new commits do not cancel earlier check runs. Independent tag pushes do not trigger this pipeline.

1. **Build once:** create CI and runtime images using `uv sync --frozen`; export them as checksum-verified Actions artifacts retained for one day. Runtime dependencies are installed separately from developer tools.
2. **Parallel jobs:** pytest (plus an installed-runtime import smoke test), mypy, Ruff lint/format, ty, Bandit, full-history Gitleaks, and Trivy against the actual runtime archive.
3. **Security gate:** Trivy fails on HIGH or CRITICAL findings, including unfixed findings. Scanner/network failures also fail the job. There are no blanket security bypasses or `continue-on-error` steps.
4. **Merged-main-only release:** after *every* check passes for that exact main SHA, the GitHub API must associate it with a PR merged into `main` whose `merge_commit_sha` matches. Direct pushes and open PRs cannot publish. The version in `pyproject.toml` determines `vX.Y.Z`; an existing release for that version is skipped. API errors fail closed. A separate release job verifies the installed runtime version, pushes the **same checked image without rebuilding** to GHCR, verifies its image ID, and creates the tag and GitHub Release at the checked main SHA with its registry digest attached. Only that job has package/content write permissions.

Maintainers: update the project version and lockfile together in a reviewed PR, then merge when ready to publish. Successful checks for the merged main commit trigger publication automatically if that version has no release. An existing tag without a corresponding release is treated as an error requiring manual resolution rather than silently repointed. A pre-existing GHCR version image is never overwritten: only an identical checked image may resume missing release steps; a different image ID or registry error fails closed. Configure branch protection to require PR review and checks as appropriate; this change does not modify repository protection. The workflow never deploys anything. Publication is intentionally not tested end-to-end from a PR, and unit-test success alone does not verify a real release.

Strict runtime security findings can block a release even if application tests pass. Fix or replace affected dependencies; do not bypass the gate. This pipeline is not evidence that any image has already been published.

## License

[MIT](LICENSE).
