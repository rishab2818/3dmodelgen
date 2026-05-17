"""Stage 2: initial 3D generation.

Calls the configured GPUBackend.generate(). In mock mode this returns the cube fixture.
The .obj bytes are written into the stage directory; downstream stages read by path.
"""

from __future__ import annotations

from pathlib import Path

from m3d_backend.gpu.base import GenerateRequest, GPUBackend
from m3d_backend.util.paths import input_dir, stage_dir


async def run(
    *,
    backend: GPUBackend,
    temp_dir: Path,
    job_id: str,
    iteration: int,
    model: str,
    seed: int,
    idempotency_key: str,
) -> tuple[Path, dict[str, object]]:
    out_dir = stage_dir(temp_dir, job_id, iteration, "generate")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Collect the preprocessed images.
    in_dir = input_dir(temp_dir, job_id)
    preprocessed = sorted(p for p in in_dir.iterdir() if p.name.startswith("preprocessed_"))
    if not preprocessed:
        raise FileNotFoundError(f"No preprocessed images in {in_dir}")

    req = GenerateRequest(
        job_id=job_id,
        iteration=iteration,
        stage="generate",
        model=model,
        image_paths=preprocessed,
        seed=seed,
        idempotency_key=idempotency_key,
    )
    resp = await backend.generate(req)

    mesh_path = out_dir / "mesh.obj"
    mesh_path.write_bytes(resp.mesh_obj_bytes)

    if resp.albedo_png_bytes is not None:
        (out_dir / "albedo.png").write_bytes(resp.albedo_png_bytes)

    meta = {
        "model": resp.meta.model,
        "revision": resp.meta.revision,
        "seed": resp.meta.seed,
        "runtime_ms": resp.meta.runtime_ms,
        "vram_peak_mb": resp.meta.vram_peak_mb,
        "provider": resp.meta.provider,
        "tri_count": resp.meta.tri_count,
        "cached": resp.meta.cached,
    }
    return mesh_path, meta
