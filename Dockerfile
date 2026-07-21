# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -e .

ENV PYTHONPATH=/app/src
ENV TOKENOPS_CONFIG=src/tokenops/config/default.yaml
ENV TOKENOPS_DB=/data/tokenops.db

VOLUME ["/data"]

EXPOSE 7700 8501
CMD ["python", "-m", "tokenops.server"]
