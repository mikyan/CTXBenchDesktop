FROM node:22.22.0-bookworm-slim

ARG PI_VERSION=0.84.4

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash ca-certificates git jq openssh-client patch python3 python3-pip python3-venv ripgrep tini \
    && rm -rf /var/lib/apt/lists/* \
    && npm install --global --ignore-scripts "@earendil-works/pi-coding-agent@${PI_VERSION}" \
    && npm cache clean --force

RUN useradd --create-home --uid 10001 --shell /bin/bash ctxbench \
    && mkdir -p /workspace /ctxbench/output /home/ctxbench/.pi/agent/skills \
    && chown -R ctxbench:ctxbench /workspace /ctxbench /home/ctxbench/.pi

COPY --chown=ctxbench:ctxbench docker/agent-pi/entrypoint.mjs /opt/ctxbench/entrypoint.mjs
COPY --chown=ctxbench:ctxbench docker/agent-pi/mock-pi.mjs /opt/ctxbench/mock-pi.mjs
COPY --chown=ctxbench:ctxbench docker/agent-pi/workflow-runtime.mjs /opt/ctxbench/workflow-runtime.mjs
LABEL io.ctxbench.workflow="1"

ENV HOME=/home/ctxbench \
    PI_NO_UPDATE_NOTIFIER=1 \
    NODE_NO_WARNINGS=1

USER ctxbench
WORKDIR /workspace
ENTRYPOINT ["/usr/bin/tini", "--", "node", "/opt/ctxbench/entrypoint.mjs"]
