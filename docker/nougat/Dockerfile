FROM vllm/vllm-openai@sha256:c75fe0c891828ea9ac316139098989114a9da5d362a07efece1710dd9dbf985f

ARG DEBIAN_FRONTEND=noninteractive

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10 \
    VIRTUAL_ENV=/opt/newsroom-venv \
    PATH=/opt/newsroom-venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    NOUGAT_MODEL=0.1.0-base \
    HF_HOME=/home/app/.cache/huggingface \
    TORCH_HOME=/home/app/.cache/torch

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3 /usr/local/bin/python

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
    python3 -m venv --system-site-packages "${VIRTUAL_ENV}" \
    && python -m pip install --upgrade pip "setuptools<81" wheel \
    && python -m pip install "numpy==1.26.4" \
    && python -m pip install \
        --constraint /tmp/nougat-constraints.txt \
        -e ".[ocr]" \
    && mkdir -p /workspace/.newsroom /home/app/.cache \
    && chown -R app:app /workspace /home/app

COPY docker/nougat/entrypoint.sh /usr/local/bin/newsroom-nougat
RUN chmod +x /usr/local/bin/newsroom-nougat

USER app

VOLUME ["/home/app/.cache"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import shutil, sys; sys.exit(0 if shutil.which('nougat') else 1)"

ENTRYPOINT ["newsroom-nougat"]
CMD ["--help"]
