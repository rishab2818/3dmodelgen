"""Stage 6: decide whether to stop / refine. Pure logic, no GPU.

The full taxonomy is in docs/QUALITY_RUBRIC.md §4–5. M1 implements only the stop decision
and the simplest refinement action (``regenerate_with_new_seed``).
"""

from __future__ import annotations

from typing import Any, Literal

RefinementAction = Literal[
    "stop",
    "regenerate_with_new_seed",
    "regenerate_with_higher_capacity",
    "texture_refine_only",
    "mesh_repair",
]


def decide(
    *,
    report: dict[str, Any],
    iteration: int,
    max_iterations: int,
    target_quality: float,
) -> RefinementAction:
    score = float(report.get("overall_score", 0.0))
    if score >= target_quality:
        return "stop"
    if iteration >= max_iterations:
        return "stop"
    # M1: always try a different seed. The richer planner (silhouette / clip / dino-based)
    # lands in M3 alongside the real evaluator.
    return "regenerate_with_new_seed"
