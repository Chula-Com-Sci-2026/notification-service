FROM ghcr.io/astral-sh/uv:python3.14-alpine

LABEL description="Notification Service"
LABEL maintainer="Tinnapop Duangtha <tinnapopduangtha@gmail.com>"

# Ref: https://docs.astral.sh/uv/guides/integration/docker/#compiling-bytecode
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#caching
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app/

# Place executables in the environment at the front of the path
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#using-the-environment
ENV PATH="/app/.venv/bin:$PATH"

# Install dependencies
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#intermediate-layers
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-workspace

COPY ./scripts /app/scripts
COPY ./pyproject.toml ./alembic.ini /app/
COPY ./app /app/app

# Sync the project
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#intermediate-layers
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen

EXPOSE 8000

# Start FastAPI with 4 Uvicorn workers (adjust for your workload). The app is
# located via the [tool.fastapi] entrypoint in pyproject.toml.
CMD ["fastapi", "run", "--workers", "4", "app/main.py"]
