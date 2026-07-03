FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        libgl1 \
        libglib2.0-0 \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --upgrade pip \
    && python -m pip install 'marker-pdf[full]>=1.8.0'

WORKDIR /workspace

ENTRYPOINT []
