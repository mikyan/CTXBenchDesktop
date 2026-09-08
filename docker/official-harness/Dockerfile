FROM python:3.11.14-slim-bookworm
LABEL io.ctxbench.image-sources="1"

ARG AGENTBENCH_COMMIT=da299c4c6b14a9abad2ceef8c751f6c45c543656
# v4.1.0 matches the pinned original Verified snapshot (v5 requires eval_script etc.).
ARG SWEBENCH_COMMIT=726c5461e2ef52d83cf1ea2107870a8bb3328d57

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates docker.io git \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/SWE-bench/SWE-bench.git /opt/swebench \
    && git -C /opt/swebench checkout "${SWEBENCH_COMMIT}" \
    && git clone https://github.com/eth-sri/agentbench.git /opt/agentbench \
    && git -C /opt/agentbench checkout "${AGENTBENCH_COMMIT}" \
    && pip install --no-cache-dir /opt/swebench /opt/agentbench \
    && rm -rf /root/.cache/pip

COPY docker/official-harness/harness.py /opt/ctxbench/harness.py
COPY docker/official-harness/swe_image.py /opt/ctxbench/swe_image.py
COPY docker/official-harness/policy.py /opt/ctxbench/policy.py
COPY docker/official-harness/grade_validation.py /opt/ctxbench/grade_validation.py
COPY docker/official-harness/agentbench_environment.py /opt/ctxbench/agentbench_environment.py

WORKDIR /data
ENTRYPOINT ["python", "/opt/ctxbench/harness.py"]
