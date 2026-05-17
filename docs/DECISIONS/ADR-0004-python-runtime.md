# ADR-0004: Python runtime — 3.10 via uv

**Status:** Accepted
**Date:** 2026-05-16
**Deciders:** user, Claude

## Context

The Python ML ecosystem in 2026 still drags on:

- **TripoSR** — depends on `torchmcubes` which is happiest on Python 3.9–3.10.
- **Hunyuan3D-2** — official requirements pin 3.10.
- **rembg** — fine on 3.10–3.12.
- **PyTorch CUDA wheels** — currently best-tested on 3.10/3.11 for the Colab T4.

The dev machine already has Python 3.12.10 globally. The product needs 3.10 for the AI pieces. We must not pollute the global Python, and we must keep dependency resolution snappy.

## Decision

- **Python 3.10.x** for the project, managed by **uv**.
- `uv python install 3.10` provides the interpreter.
- `pyproject.toml` + `uv.lock` is the dependency source of truth — no `requirements.txt`, no `setup.py`, no `Pipfile`.
- Two top-level workspace members:
  - `backend/` — the orchestrator (FastAPI, async I/O, no torch).
  - `ai_models/` — adapters + the remote server entrypoint (torch, transformers, etc.).
- Blender's bundled Python (3.11.x inside Blender 5.x) is **separate** and stdlib-only for our scripts. We do not install packages into Blender's Python.

## Consequences

**Good**
- `uv` is dramatically faster than pip + venv. Cold install of the backend env: ~20 s vs. several minutes.
- `uv.lock` is reproducible across machines. CI hits cache on dependency change → fast.
- 3.10 maximizes compatibility with the AI stack.
- Workspaces let `backend` be torch-free, so the orchestrator stays a fast-booting Python process even when AI deps are big.

**Bad**
- A second Python on the system means tooling (VS Code, terminal) needs to know which to use. We document this in `backend/CLAUDE.md`.
- Some libraries are starting to drop 3.10 support. We will revisit by mid-2027.

**Neutral**
- `uv` is from Astral, the same shop that makes Ruff. We are also adopting Ruff for lint/format, so this is one ecosystem, not three.

## Alternatives considered

**conda / mamba.** Mature for ML environments. Rejected because: (a) conda packages of recent diffusion-stack libs lag pip; (b) conda's solver is slow; (c) conda on Windows has historically been clunky in subprocess scenarios; (d) `uv` handles the same job 10x faster.

**poetry + pyenv.** Adequate but two tools instead of one. `uv` does both.

**Python 3.11 or 3.12.** Better in many ways but breaks compatibility with TripoSR's `torchmcubes` (last update was on 3.10). Not worth the fight when 3.10 just works.
