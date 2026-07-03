ARG MARKER_BASE_IMAGE=pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime
FROM ${MARKER_BASE_IMAGE}

ENV PYTHONUNBUFFERED=1 \
    TORCH_DEVICE=cuda \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        libgl1 \
        libglib2.0-0 \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --no-cache-dir --upgrade pip \
    && python3 -m pip install --no-cache-dir 'marker-pdf[full]>=1.8.0'

WORKDIR /workspace

ENTRYPOINT []
