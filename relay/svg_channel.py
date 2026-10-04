"""The pixel bottleneck: SVG in, rendered PNG out.

The model writes SVG source (byte-capped); the harness sanitizes it,
rasterizes it deterministically, and ONLY the pixels reach the successor —
a lossy, modality-crossing self-communication channel (text -> vector ->
raster -> vision).

Renderer: pluggable and PINNED per snapshot — scores are
renderer-conditioned by design, so the renderer identity is part of the
benchmark spec and is recorded in results. Preference order when
auto-detecting: resvg (cross-platform, release default) > rsvg-convert >
qlmanage (macOS Quick Look; used for the relay-2026-07 snapshot). Pin
explicitly with RELAY_RENDERER=resvg|rsvg|qlmanage. All are verified
deterministic (identical source -> identical PNG bytes) by tests."""

from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

MAX_SVG_BYTES = 2500
RENDER_PX = 512


def active_renderer() -> str | None:
    """The pinned or auto-detected renderer name, None if none available."""
    pinned = os.environ.get("RELAY_RENDERER")
    if pinned:
        return pinned
    for name, exe in (("resvg", "resvg"), ("rsvg", "rsvg-convert"), ("qlmanage", "qlmanage")):
        if shutil.which(exe):
            return name
    return None

_FORBIDDEN = re.compile(
    r"<script|<foreignObject|href\s*=|url\s*\(|@import|<image|<iframe|<use"
    r"|<[^>]*\s+on[a-z]+\s*=|<(?:animate(?:Motion|Transform)?|set|discard)\b",
    re.IGNORECASE,
)


def sanitize_svg(source: str) -> str | None:
    """Return source after the documented pattern filters, or None.

    Reject script/image/foreign-object elements, resource-reference patterns,
    event attributes and animation elements. This is a pattern filter, not
    a complete SVG allowlist or renderer-independent security guarantee.
    """
    if not isinstance(source, str):
        return None
    src = source.strip()
    if not src.startswith("<svg") or "</svg>" not in src:
        return None
    src = src[: src.rindex("</svg>") + 6]
    if len(src.encode("utf-8")) > MAX_SVG_BYTES:
        return None
    if _FORBIDDEN.search(src):
        return None
    if "xmlns" not in src:
        src = src.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
    return src


def render_svg(source: str) -> bytes | None:
    """Rasterize sanitized SVG to PNG bytes at RENDER_PX, white-backed,
    via the pinned/auto-detected renderer."""
    renderer = active_renderer()
    if renderer is None:
        return None
    with tempfile.TemporaryDirectory() as td:
        svg_path = Path(td) / "note.svg"
        png_path = Path(td) / "note.png"
        svg_path.write_text(source, encoding="utf-8")
        px = str(RENDER_PX)
        commands = {
            "resvg": ["resvg", "--width", px, "--height", px,
                      "--background", "white", str(svg_path), str(png_path)],
            "rsvg": ["rsvg-convert", "-w", px, "-h", px, "-b", "white",
                     "-o", str(png_path), str(svg_path)],
            "qlmanage": ["qlmanage", "-t", "-s", px, "-o", td, str(svg_path)],
        }
        if renderer not in commands:
            return None
        try:
            subprocess.run(commands[renderer], capture_output=True, timeout=20, check=True)
        except (subprocess.SubprocessError, OSError):
            return None
        if renderer == "qlmanage":
            png_path = Path(td) / "note.svg.png"
        if not png_path.exists():
            return None
        return png_path.read_bytes()


def png_b64(png: bytes) -> str:
    return base64.b64encode(png).decode("ascii")
