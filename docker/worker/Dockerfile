FROM python:3.13.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CTXBENCH_DATA_DIR=/var/lib/ctxbench

WORKDIR /opt/ctxbench
COPY worker/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --requirement requirements.txt

COPY worker/ctxbench_worker ./ctxbench_worker
COPY skills ./skills

EXPOSE 48173
CMD ["python", "-m", "ctxbench_worker"]
