# syntax=docker/dockerfile:1
# Multi-stage: the Vue SPA is built first, uv resolves Python deps in the
# builder, and the runtime ships only the venv + app + built frontend.
FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim-bookworm AS runtime
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY migrations ./migrations
COPY alembic.ini ./
COPY --from=web /web/dist /app/web/dist
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH" \
    LIBARR_DATABASE_URL="sqlite:////data/libarr.db" \
    LIBARR_CONVERSION_OUT_DIR="/data/converted"

RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 1000 libarr \
    && useradd -g libarr -u 1000 -m libarr \
    && mkdir -p /data /config \
    && chown -R libarr:libarr /data /config \
    && chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 8787
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "libarr.main:app", "--host", "0.0.0.0", "--port", "8787"]
