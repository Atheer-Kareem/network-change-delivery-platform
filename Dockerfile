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

FROM base AS application
COPY pyproject.toml uv.lock README.md ansible.cfg ./
COPY src ./src
COPY ansible ./ansible
RUN uv sync --frozen --no-group dev \
    && .venv/bin/ansible-galaxy collection install \
      --requirements-file ansible/requirements.yml \
      --collections-path /opt/ansible/collections

FROM application AS quality-base
COPY . .
RUN chmod a+rx /app/scripts /app/infrastructure \
    && chmod -R a=rX \
      /app/src \
      /app/scripts/observability \
      /app/infrastructure/observability \
    && uv sync --frozen --all-groups

FROM quality-base AS quality
RUN uv run ruff check . \
    && uv run ruff format --check . \
    && uv run pytest \
    && uv run ansible-lint \
    && uv build

FROM application AS promotion
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
COPY fixtures/batfish ./fixtures/batfish
COPY deployments/live/promotion ./deployments/live/promotion
COPY scripts/buildkite/batfish_ready.py scripts/buildkite/render_assurance_annotation.py ./scripts/buildkite/
RUN chmod -R a=rX \
      /app/.venv \
      /app/src \
      /app/fixtures/batfish \
      /app/deployments/live/promotion \
      /app/scripts/buildkite

FROM ${PYTHON_IMAGE} AS runtime
ENV PATH="/app/.venv/bin:${PATH}" \
    ANSIBLE_CONFIG="/app/ansible.cfg" \
    ANSIBLE_COLLECTIONS_PATH="/opt/ansible/collections" \
    NCDP_PROJECT_ROOT="/app" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN groupadd --system ncdp \
    && useradd --system --gid ncdp --home-dir /app --create-home ncdp
WORKDIR /app
COPY --from=application --chown=ncdp:ncdp /app/.venv /app/.venv
COPY --from=application /opt/ansible/collections /opt/ansible/collections
COPY --from=application --chown=ncdp:ncdp /app/src /app/src
COPY --chown=ncdp:ncdp ansible.cfg ./
COPY --chown=ncdp:ncdp ansible ./ansible
USER ncdp
ENTRYPOINT ["ncdp"]
