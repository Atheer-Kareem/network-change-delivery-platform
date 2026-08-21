# syntax=docker/dockerfile:1
ARG PYTHON_IMAGE=python:3.12-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.2@sha256:069a51314a7bb6031777a9273205fe1b0b19e914ef418207d1338b268df641dd

FROM ${UV_IMAGE} AS uv
FROM ${PYTHON_IMAGE} AS base
COPY --from=uv /uv /uvx /bin/
ENV UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app

FROM base AS quality
COPY . .
RUN uv sync --frozen --all-groups \
    && uv run ruff check . \
    && uv run ruff format --check . \
    && uv run pytest \
    && uv build

FROM base AS build
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv build --wheel

FROM ${PYTHON_IMAGE} AS runtime
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN groupadd --system ncdp \
    && useradd --system --gid ncdp --home-dir /app --create-home ncdp
WORKDIR /app
COPY --from=uv /uv /uvx /bin/
COPY --from=build /app/dist/*.whl /tmp/
RUN uv venv /app/.venv \
    && uv pip install --python /app/.venv/bin/python /tmp/*.whl \
    && rm -f /tmp/*.whl \
    && chown -R ncdp:ncdp /app
USER ncdp
ENTRYPOINT ["ncdp"]
