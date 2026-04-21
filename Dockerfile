# Agent container. Python-only; no shell tools beyond what pip needs.
FROM python:3.11-slim-bookworm AS base

# Non-root UID; must match host mount ownership for the bridge socket if chmod'd.
ARG AGENT_UID=10001
ARG AGENT_GID=10001
RUN groupadd --system --gid ${AGENT_GID} agent \
 && useradd  --system --uid ${AGENT_UID} --gid agent --home-dir /app --shell /usr/sbin/nologin agent

WORKDIR /app

# Minimal system deps. No build-essential in the final image.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tini \
 && rm -rf /var/lib/apt/lists/*

# Install dependencies first for caching.
COPY agent/pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir "httpx>=0.27" "pydantic>=2.9" "pyyaml>=6.0"

# App code.
COPY agent/src/agent /app/agent

# Data + memory live on a named volume. /safety is bind-mounted read-only at runtime.
RUN mkdir -p /data /memory /safety && chown -R agent:agent /app /data /memory

USER agent

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    AGENT_MODE=smoke \
    BRIDGE_SOCKET=/run/claude-bridge.sock \
    AGENT_STATE=/data/state.json

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "agent.main"]
