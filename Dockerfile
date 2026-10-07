# Imagen del CRM para un servidor (Azure Container Apps, o cualquier Docker).
# La base de datos vive en /data, que debe ser un volumen persistente.
FROM python:3.12-slim

# uv fijado a la misma versión que en el PC de desarrollo.
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Primero solo las dependencias: esta capa se reutiliza mientras no cambie uv.lock.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    CRM_HOST=0.0.0.0 \
    CRM_PORT=8000 \
    CRM_DB_PATH=/data/crm.db \
    CRM_SECURE_COOKIES=true

EXPOSE 8000

# Cada arranque aplica las migraciones pendientes (no hace nada si ya está al día).
CMD ["sh", "-c", "alembic upgrade head && crm serve"]
