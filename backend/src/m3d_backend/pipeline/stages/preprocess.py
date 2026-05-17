"""Stage 1: preprocess input image(s).

M2 implementation:
  1. Decode each input image with Pillow (rejects junk early).
  2. Background removal via rembg (gated by ``Settings.bg_removal_enabled``; disabled
     in tests + mock mode to avoid the 170 MB model download).
  3. Resize to a square canvas of ``preprocess_target_size`` (default 512 px),
     preserving aspect and padding with transparent.
  4. Save deterministically as ``preprocessed_NN.png`` so generation cache keys hit.

Determinism: the same input bytes produce byte-identical output. That is what makes the
generation cache (key = sha256(preprocessed_bytes || model || revision || seed || params))
useful.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from m3d_backend.util.paths import input_dir

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage


def run(
    *,
    temp_dir: Path,
    job_id: str,
    input_images: list[Path],
    bg_removal_enabled: bool,
    bg_removal_model: str = "u2net",
    target_size: int = 512,
) -> list[Path]:
    out_dir = input_dir(temp_dir, job_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    bg_remover = _make_bg_remover(bg_removal_model) if bg_removal_enabled else None

    written: list[Path] = []
    for i, src in enumerate(input_images):
        if not src.exists():
            raise FileNotFoundError(f"Input image not found: {src}")
        img = _load_rgba(src)
        if bg_remover is not None:
            img = bg_remover(img)
        img = _fit_to_canvas(img, target_size)
        dst = out_dir / f"preprocessed_{i:02d}.png"
        # Pillow PNG output is deterministic when we pin optimize=False and disable
        # interlacing — both defaults.
        img.save(dst, format="PNG")
        written.append(dst)

    # Keep an "original" alongside (first input) for the evaluator to compare against.
    original_src = input_images[0]
    original_img = _load_rgba(original_src)
    original_out = out_dir / "original.png"
    original_img.save(original_out, format="PNG")
    written.append(original_out)

    return written


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_rgba(path: Path) -> PILImage:
    """Open with Pillow, convert to RGBA, verify size sanity. Raises early on garbage."""
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError(f"Image exceeds 32 MB limit: {path}")
    img = Image.open(path)
    img.load()  # force decode now so we raise here, not later
    return img.convert("RGBA")


def _fit_to_canvas(img: PILImage, target: int) -> PILImage:
    """Resize ``img`` to fit inside a ``target``x``target`` canvas, preserving aspect,
    padded with transparent. The output is deterministic given the input.
    """
    w, h = img.size
    if w == 0 or h == 0:
        raise ValueError("zero-dimension image after preprocessing")
    ratio = target / max(w, h)
    new_size = (max(1, int(round(w * ratio))), max(1, int(round(h * ratio))))
    resized = img.resize(new_size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (target, target), (0, 0, 0, 0))
    canvas.paste(
        resized,
        ((target - new_size[0]) // 2, (target - new_size[1]) // 2),
        resized,
    )
    return canvas


def _make_bg_remover(model_name: str):  # type: ignore[no-untyped-def]
    """Return a callable that removes the background of a PIL image.

    Imports rembg lazily so a backend missing the ONNX runtime can still boot for the
    mock pipeline (set ``M3D_BG_REMOVAL_ENABLED=false``).
    """
    from rembg import new_session, remove  # type: ignore[import-untyped]

    session = new_session(model_name=model_name)

    def remove_bg(img: PILImage) -> PILImage:
        out = remove(img, session=session)
        # rembg returns a PIL image when given one, but type stubs are lax.
        if not isinstance(out, Image.Image):
            raise TypeError(f"rembg.remove returned {type(out).__name__}, expected PIL image")
        return out.convert("RGBA")

    return remove_bg
