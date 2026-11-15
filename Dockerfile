# Tool images are copied only into CI, never into the runtime image.
FROM ghcr.io/gitleaks/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f AS gitleaks
FROM aquasec/trivy:0.76.2@sha256:8f6bb947dbc528902e11f2f5be52f7b519f6a39d5d148f41166f2040499768fb AS trivy
FROM ghcr.io/astral-sh/uv:0.13.8@sha256:5cc1805e2426484abca4ad46ea783bab281fdb225fd82d8ce6d66a81254bac85 AS uv

FROM python:3.14-slim-trixie@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN apt-get update && apt-get upgrade -y

FROM base AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src/ src/
RUN uv sync --frozen --no-dev --no-editable

FROM builder AS ci
RUN uv sync --frozen --no-editable && apt-get update && apt-get install -y --no-install-recommends git ca-certificates
COPY --from=gitleaks /usr/bin/gitleaks /usr/local/bin/gitleaks
COPY --from=trivy /usr/local/bin/trivy /usr/local/bin/trivy
ENV PATH="/app/.venv/bin:$PATH"
COPY tests/ tests/
CMD ["pytest"]

FROM base AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && groupadd --gid 1000 bot && useradd --uid 1000 --gid bot --create-home bot
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" DOWNLOAD_DIR=/app/downloads
RUN mkdir -p /app/data /app/downloads && chown bot:bot /app/data /app/downloads
USER bot
CMD ["python", "-m", "src"]
