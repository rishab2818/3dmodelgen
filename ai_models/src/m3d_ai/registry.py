"""Read the pinned model registry from registry.yaml. Single source of truth for
``(repo, revision, min_vram_mb)`` per model name. Never use ``revision="main"``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class ModelEntry:
    name: str
    repo: str
    revision: str
    min_vram_mb: int
    requires_license_acceptance: bool = False
    available_in: tuple[str, ...] = ("remote", "local")


_REGISTRY_FILE = Path(__file__).parent / "registry.yaml"


def load_registry(path: Path | None = None) -> dict[str, ModelEntry]:
    """Return a mapping of generator-name → ModelEntry."""
    p = path or _REGISTRY_FILE
    raw = yaml.safe_load(p.read_text())
    gens = raw.get("generators", {})
    out: dict[str, ModelEntry] = {}
    for name, spec in gens.items():
        out[name] = ModelEntry(
            name=name,
            repo=str(spec["repo"]),
            revision=str(spec["revision"]),
            min_vram_mb=int(spec.get("min_vram_mb", 0)),
            requires_license_acceptance=bool(spec.get("requires_license_acceptance", False)),
            available_in=tuple(spec.get("available_in", ("remote", "local"))),
        )
    return out


def get(name: str) -> ModelEntry:
    reg = load_registry()
    if name not in reg:
        raise KeyError(f"Unknown generator: {name!r}. Known: {sorted(reg)}")
    return reg[name]
