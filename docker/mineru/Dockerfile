ARG MINERU_BASE_IMAGE=vllm/vllm-openai:v0.21.0-cu129
ARG MINERU_PRELOAD_MODELS=1
FROM ${MINERU_BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    MINERU_MODEL_SOURCE=local

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fontconfig \
        fonts-noto-cjk \
        fonts-noto-core \
        libgl1 \
    && fc-cache -fv \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --no-cache-dir -U \
        'mineru[core]>=3.4.0' \
        'pdftext==0.6.3' \
        --break-system-packages

RUN if [ "${MINERU_PRELOAD_MODELS}" = "1" ]; then \
        mineru-models-download -s huggingface -m all; \
    else \
        echo "Skipping MinerU model preload; mount a persistent cache or preload at runtime."; \
    fi

WORKDIR /workspace
ENTRYPOINT ["/bin/bash", "-c", "export MINERU_MODEL_SOURCE=local && exec \"$@\"", "--"]
