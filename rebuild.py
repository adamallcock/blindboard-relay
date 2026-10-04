#!/usr/bin/env python3
"""Verify this repository export and reproduce values without model calls."""

import hashlib
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    for row in (ROOT / "SHA256SUMS").read_text().splitlines():
        expected, rel = row.split("  ", 1)
        path = ROOT / rel
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise SystemExit(f"Checksum mismatch: {rel}")
    watched = [ROOT / "paper/tables/relay_macros.tex", ROOT / "results/relay/analysis.json"]
    before = {path: path.read_bytes() for path in watched}
    for script in ("relay_manifest.py", "check_vendored.py", "relay_analysis.py"):
        subprocess.run([sys.executable, f"scripts/{script}"], cwd=ROOT, check=True)
    for path, content in before.items():
        if path.read_bytes() != content:
            raise SystemExit(f"Numerical reproduction mismatch: {path.relative_to(ROOT)}")
    print("PASS: all shipped checksums, evidence selection, vendored code and numerical reproduction")


if __name__ == "__main__":
    main()
