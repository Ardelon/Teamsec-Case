FROM python:3.12-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    pkg-config \
    libssl-dev \
    libpq-dev \
    patchelf \
    && rm -rf /var/lib/apt/lists/*

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

WORKDIR /app

COPY api/requirements.txt /app/api/requirements.txt
RUN pip install --no-cache-dir -r /app/api/requirements.txt maturin

COPY adapter /app/adapter
RUN cd /app/adapter && maturin build --release --out /wheels && pip install /wheels/*.whl

COPY api /app/api

WORKDIR /app/api

CMD ["celery", "-A", "config", "worker", "--loglevel=info", "--concurrency=3", "--prefetch-multiplier=1"]