# ── Stage 1: Build ──────────────────────────────────────────────────────────────
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS builder

WORKDIR /app

# Copy dependency manifests first for layer caching.
COPY pyproject.toml uv.lock* ./

# Install production dependencies into a virtual-env at /app/.venv
RUN uv sync --frozen --no-dev --no-install-project

# Copy source code and install the project itself.
COPY src/ src/
RUN uv sync --frozen --no-dev


# ── Stage 2: Runtime ────────────────────────────────────────────────────────────
FROM python:3.14-slim-bookworm AS runtime

# Install gallery-dl system dependency (ffmpeg for merging streams).
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Create a non-root user.
RUN groupadd --gid 1000 bot && \
    useradd --uid 1000 --gid bot --shell /bin/bash --create-home bot

WORKDIR /app

# Copy the virtual-env with all installed packages from builder stage.
COPY --from=builder /app/.venv /app/.venv

# Ensure venv binaries are on PATH.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Prepare download directory.
RUN mkdir -p /tmp/tg-downloads && chown bot:bot /tmp/tg-downloads

USER bot

CMD ["python", "-m", "src"]
