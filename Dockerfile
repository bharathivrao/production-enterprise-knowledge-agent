FROM ghcr.io/astral-sh/uv:0.11.3 AS uvbin

FROM python:3.14-slim AS build
COPY --from=uvbin /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.14-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 agent \
    && useradd --system --uid 10001 --gid agent --home-dir /app agent
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY --chown=agent:agent app ./app
COPY --chown=agent:agent scripts ./scripts
COPY --chown=agent:agent pyproject.toml uv.lock ./
USER agent
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
