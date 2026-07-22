# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml README.md ./
COPY src ./src
COPY examples ./examples
COPY benchmarking ./benchmarking
COPY scripts ./scripts
COPY run.py run_triad.py run_brief.py ./

RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -e ".[examples]"

ENV PYTHONPATH=/app
ENV TOKENOPS_CONFIG=src/tokenops/config/default.yaml
ENV TOKENOPS_DB=/data/tokenops.db

VOLUME ["/data"]

EXPOSE 7700 8001 8002 8011 8012 8013 8021 8022 8023 8501
CMD ["python", "-m", "tokenops.server"]
