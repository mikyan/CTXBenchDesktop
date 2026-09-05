FROM python:3.13.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CTXBENCH_DATA_DIR=/var/lib/ctxbench

WORKDIR /opt/ctxbench
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
COPY worker/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --requirement requirements.txt

COPY worker/ctxbench_worker ./ctxbench_worker
COPY skills ./skills

EXPOSE 48173
CMD ["python", "-m", "ctxbench_worker"]
