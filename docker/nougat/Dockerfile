FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim@sha256:4f5d923c9dcea037f57bda425dd209f3ec643da2f0b74227f68d09dab0b3bb36

ARG DEBIAN_FRONTEND=noninteractive

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NOUGAT_MODEL=0.1.0-base \
    HF_HOME=/home/app/.cache/huggingface \
    TORCH_HOME=/home/app/.cache/torch

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system app \
    && useradd --system --gid app --create-home --home-dir /home/app app

WORKDIR /workspace

COPY docker/nougat/constraints.txt /tmp/nougat-constraints.txt
COPY pyproject.toml README.md ./
COPY business ./business
COPY framework ./framework
COPY infrastructure ./infrastructure
COPY interfaces ./interfaces

RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install "numpy==1.26.4" \
    && python -m pip install \
        --index-url https://download.pytorch.org/whl/cpu \
        "torch==2.2.2+cpu" \
        "torchvision==0.17.2+cpu" \
    && python -m pip install \
        --constraint /tmp/nougat-constraints.txt \
        -e ".[ocr]" \
    && mkdir -p /workspace/.newsroom /home/app/.cache \
    && chown -R app:app /workspace /home/app

COPY docker/nougat/entrypoint.sh /usr/local/bin/newsroom-nougat
RUN chmod +x /usr/local/bin/newsroom-nougat

USER app

VOLUME ["/home/app/.cache", "/workspace/.newsroom"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import shutil, sys; sys.exit(0 if shutil.which('nougat') else 1)"

ENTRYPOINT ["newsroom-nougat"]
CMD ["--help"]
