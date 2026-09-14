# syntax=docker/dockerfile:1.17-labs
ARG BASE_IMAGE=ubuntu:24.04
# Global build args: defaults for every stage. Re-declared with a bare `ARG`
# inside each stage that uses them, which inherits the value set here.
ARG PROJECT_PATH=/app
ARG NONROOT_USERNAME=ubuntu

FROM $BASE_IMAGE AS python-base
ARG PROJECT_PATH
ARG NONROOT_USERNAME=ubuntu

# python
ENV PYTHONUNBUFFERED=1 \
    \
    # pip
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    \
    # paths
    # this is where our requirements + virtual environment will live
    VENV_PATH="${PROJECT_PATH}/.venv"

# prepend venv to path
ENV PATH="$VENV_PATH/bin:$PATH"

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt update \
    && apt install -y --no-install-recommends \
        python3-dev \
        ca-certificates

################################################################################

FROM python-base AS prod-prepare
ARG DEBIAN_FRONTEND=noninteractive
ARG NONROOT_USERNAME
ARG PROJECT_PATH

    # Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy \
    # uv
    UV_CACHE_DIR="/home/${NONROOT_USERNAME}/.cache/uv"

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt update \
    && apt install -y --no-install-recommends \
        build-essential

RUN useradd -ms /bin/bash ${NONROOT_USERNAME} --user-group || true
# A WORKDIR-created directory is root-owned even under USER, which would make
# `uv sync` (run as the non-root user) fail to write the venv. Create + chown it.
RUN mkdir -p ${PROJECT_PATH} && chown ${NONROOT_USERNAME}:${NONROOT_USERNAME} ${PROJECT_PATH}
USER ${NONROOT_USERNAME}
WORKDIR ${PROJECT_PATH}

# Install runtime dependencies only. The project is a few flat modules
# (server.py, moodle_client.py, client.py) that are copied into the prod stage
# and run directly, so there is no wheel to build/install here.
RUN --mount=type=cache,dst=${UV_CACHE_DIR},uid=1000,gid=1000 \
    --mount=from=ghcr.io/astral-sh/uv:latest,source=/uv,target=/bin/uv \
    --mount=type=bind,source=pyproject.toml,target=${PROJECT_PATH}/pyproject.toml \
    --mount=type=bind,source=uv.lock,target=${PROJECT_PATH}/uv.lock \
    uv sync --frozen --no-install-project --no-install-workspace --no-dev

# for compatibility with prod stage COPY when uv is using python from /usr/bin
RUN mkdir -p /home/${NONROOT_USERNAME}/.local/share/uv/python

################################################################################

FROM python-base AS prod
ARG DEBIAN_FRONTEND=noninteractive
ARG NONROOT_USERNAME
ARG PROJECT_PATH

WORKDIR ${PROJECT_PATH}

RUN chown ${NONROOT_USERNAME}:${NONROOT_USERNAME} ${PROJECT_PATH}

COPY --chown=${NONROOT_USERNAME}:${NONROOT_USERNAME} --from=prod-prepare /home/${NONROOT_USERNAME}/.local/share/uv/python /home/${NONROOT_USERNAME}/.local/share/uv/python
COPY --chown=${NONROOT_USERNAME}:${NONROOT_USERNAME} --from=prod-prepare ${VENV_PATH} ${VENV_PATH}

RUN useradd -ms /bin/bash ${NONROOT_USERNAME} --user-group || true
USER ${NONROOT_USERNAME}

COPY --exclude=.devcontainer/ --chown=${NONROOT_USERNAME}:${NONROOT_USERNAME} . .

# MCP server configuration (override at `docker run` time):
#   MCP_ALLOWED_HOSTS  hostnames allowed in the Host header (DNS-rebinding guard).
#                      REQUIRED for access via a domain/IP; use "*" only behind a
#                      trusted reverse proxy. Unset = localhost only.
#   MCP_HOST / MCP_PORT  bind address and port.
ENV MCP_HOST=0.0.0.0 \
    MCP_PORT=3033
EXPOSE 3033

# Run the NCCU Moodle MCP server over Streamable HTTP.
CMD ["python", "server.py", "http"]

################################################################################

FROM python-base AS dev
ARG DEBIAN_FRONTEND=noninteractive
ARG PROJECT_PATH
    # Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy \
    # uv
    UV_CACHE_DIR="/root/.cache/uv"

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
    && apt-get install --no-install-recommends -y \
        # useful tools
        git vim wget curl ca-certificates build-essential tmux

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR ${PROJECT_PATH}

CMD ["sleep", "infinity"]
