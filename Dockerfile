# Build only the public calculation runtime. The Dockerfile deliberately never
# copies the repository root wholesale, so local profiles and private sources
# cannot enter the image even if a future .dockerignore rule regresses.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS build

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN apt-get update \
    && apt-get install --yes --no-install-recommends build-essential pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ ./src/
RUN uv sync --frozen --no-dev

FROM python:3.12-slim-bookworm AS runtime

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

RUN useradd --create-home --uid 10001 appuser
COPY --from=build --chown=appuser:appuser /app/.venv /app/.venv
COPY --from=build --chown=appuser:appuser /app/src /app/src

USER appuser
EXPOSE 8080

# Deliberately one Python/Uvicorn process. The no-auth request-rate and
# single-flight calculation guards are process-local; Railway must use one
# replica/worker until a reviewed shared rate/admission control exists.
CMD ["python", "-m", "jyotish_agent.mcp_http"]
