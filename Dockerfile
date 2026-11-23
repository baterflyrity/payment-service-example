FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    HOME=/home/app

WORKDIR /app

# Версия uv зафиксирована, чтобы сборка была воспроизводимой.
RUN pip install --no-cache-dir uv==0.13.9

COPY pyproject.toml uv.lock ./
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./

# Непривилегированный пользователь с фиксированным UID: контейнер не работает
# от root. Права на нужные пути отдаются до переключения USER.
RUN uv sync --frozen --no-dev \
    && useradd --system --uid 10001 --create-home --shell /usr/sbin/nologin app \
    && chown -R app:app /app

ENV PATH="/app/.venv/bin:$PATH"

USER app

EXPOSE 8000

CMD ["uvicorn", "payment_service.entrypoints.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
