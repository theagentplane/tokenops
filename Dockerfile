# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml README.md ./
COPY src ./src
COPY bench ./bench

# Install package + deps (chronicle from git via pyproject / pip)
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -e .

ENV PYTHONPATH=/app/src:/app
ENV TOKENOPS_CONFIG=src/tokenops/config/default.yaml
ENV TOKENOPS_DB=/data/tokenops.db

VOLUME ["/data"]

# Default: control plane. Override CMD per service in compose.
EXPOSE 7700 8001 8002 8501
CMD ["python", "-m", "tokenops.server"]
