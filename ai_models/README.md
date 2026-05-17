# ai_models

GPU adapters + the FastAPI remote server. The ONLY folder in the repo allowed to import torch / transformers / diffusers.

Two deployment modes share one codebase:

- **`m3d_ai.remote_server:app`** — runs on Colab/Modal/RunPod. Loads real models.
- Same adapters imported in-process by `LocalGPUBackend` (M6) when the user has an NVIDIA box.

The dev laptop installs **only** the base deps (FastAPI + Pillow + structlog). Mock adapter works without torch. Torch + TripoSR weights live on the GPU host.

## Install

Dev laptop (no GPU):
```
uv sync --extra dev
```

GPU host (Colab):
```
uv sync --extra torch --extra dev
# plus TripoSR from github inside the notebook
```

## Run the server locally with mock adapter

```
uv run uvicorn m3d_ai.remote_server:app --port 8000
```

Rules and conventions: see `./CLAUDE.md`.
