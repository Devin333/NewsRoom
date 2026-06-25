#!/usr/bin/env python
from __future__ import annotations

import os


def main() -> int:
    model_name = os.environ.get(
        "NEWS_VISUAL_EMBEDDING_MODEL",
        "sentence-transformers/clip-ViT-L-14",
    )
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    print(f"preloading visual embedding model: {model_name}", flush=True)
    print(f"using HuggingFace endpoint: {os.environ['HF_ENDPOINT']}", flush=True)
    print("downloading safetensors snapshot into HF_HOME cache...", flush=True)
    from huggingface_hub import snapshot_download

    snapshot_path = snapshot_download(
        repo_id=model_name,
        ignore_patterns=["*.bin"],
        resume_download=True,
    )
    print(f"snapshot ready: {snapshot_path}", flush=True)

    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)
    probe = model.encode(["visual embedding dimension probe"], normalize_embeddings=True)
    dimension = int(probe.shape[-1])
    print(f"loaded {model_name}; embedding_dimension={dimension}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
