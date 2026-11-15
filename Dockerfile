# Tool images are copied only into the scan image, never into CI or runtime.
FROM ghcr.io/gitleaks/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f AS gitleaks
FROM aquasec/trivy:0.76.2@sha256:8f6bb947dbc528902e11f2f5be52f7b519f6a39d5d148f41166f2040499768fb AS trivy
FROM ghcr.io/astral-sh/uv:0.13.8@sha256:5cc1805e2426484abca4ad46ea783bab281fdb225fd82d8ce6d66a81254bac85 AS uv

# Use supported Alpine 3.24 packages for Python 3.14 and FFmpeg 8.1.
# The runtime still requires a full vulnerability scan; a base change is not proof
# that every upstream FFmpeg vulnerability is fixed.
# Install the interpreter without pip: uv manages the locked environment, and
# pip's vendored dependencies otherwise introduce a second, untracked dep set.
FROM alpine:3.24@sha256:f59abe656b692d901e184be3445e084786602108599d2a51d229c0f5a48c71bf AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
# CI passes the current date so a cached layer never pins yesterday's packages;
# without the argument every build installs fresh packages as before.
ARG APK_REFRESH=
RUN : "apk snapshot ${APK_REFRESH}" && apk upgrade --no-cache && apk add --no-cache 'python3~3.14' ca-certificates

FROM base AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
# Third-party dependencies come first: they change only with the lockfile, so
# source edits reuse these layers instead of reinstalling everything.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY README.md LICENSE ./
COPY src/ src/
RUN uv sync --frozen --no-dev --no-editable

# Developer tools are added to a copy of the dependency layer, so the CI image
# also rebuilds only its last two small layers when sources change.
FROM builder AS ci
RUN uv sync --frozen --no-editable
ENV PATH="/app/.venv/bin:$PATH"
COPY setup.cfg ./
COPY tests/ tests/
CMD ["pytest"]

# Scanners live in their own image so lint and test jobs do not download them.
FROM base AS scan
RUN apk add --no-cache git
COPY --from=gitleaks /usr/bin/gitleaks /usr/local/bin/gitleaks
COPY --from=trivy /usr/local/bin/trivy /usr/local/bin/trivy

FROM base AS runtime
RUN apk add --no-cache 'ffmpeg>=8.1.3' && addgroup -g 1000 bot && adduser -D -u 1000 -G bot bot
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" DOWNLOAD_DIR=/app/downloads
RUN mkdir -p /app/data /app/downloads && chown bot:bot /app/data /app/downloads
USER bot
CMD ["bot"]
