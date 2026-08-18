# syntax=docker/dockerfile:1
# Multi-stage build: uv resolves deps in the builder, runtime ships only the venv.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY README.md ./
COPY src ./src
# Production: bake the package in (--no-editable). Dev compose overrides with editable
# so ./src can be bind-mounted for --reload.
ARG SYNC_ARGS="--frozen --no-dev --no-editable"
RUN uv sync $SYNC_ARGS

FROM python:3.12-slim-bookworm AS runtime
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH" \
    LIBARR_DATABASE_URL="sqlite:////data/libarr.db" \
    LIBARR_DATA_DIR="/data" \
    LIBARR_LIBRARY_ROOT="/data/books" \
    LIBARR_DOWNLOAD_DIR="/data/downloads" \
    LIBARR_REDIS_URL="redis://redis:6379"

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
