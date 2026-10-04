#!/usr/bin/env python3
"""Evidence-selection manifest for the relay corpus.

`--write` pins every stored episode file (both channels), every probe.json,
and every calibration artifact: relative path, sha256, channel, prompt
version, cell identity, and seed, plus the generator's git commit. `--check`
fails closed on ANY missing, changed, added, or duplicated input — a
silently drifting or swapped episode cannot move a published number.

  uv run python scripts/relay_manifest.py --write   # deliberate re-pin
  uv run python scripts/relay_manifest.py --check   # gate mode (default)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "results/relay/MANIFEST.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect() -> dict[str, dict]:
    entries: dict[str, dict] = {}
    for chan, root in (("text", ROOT / "results/relay/llm"),
                       ("pixel", ROOT / "results/relay/svg")):
        for d in sorted(root.iterdir()):
            if not d.is_dir():
                continue
            for p in sorted(d.glob("seed*.json")):
                r = json.loads(p.read_text())["result"]
                rel = str(p.relative_to(ROOT))
                entries[rel] = {
                    "sha256": sha256(p),
                    "channel": chan,
                    "prompt_version": r.get("prompt_version"),
                    "model": r.get("model"),
                    "condition": r.get("condition"),
                    "budget": str(r.get("budget") or r.get("budget_chars")),
                    "seed": r.get("seed"),
                }
            for p in sorted(d.glob("probe.json")) + sorted(d.glob("summary.json")):
                entries[str(p.relative_to(ROOT))] = {
                    "sha256": sha256(p), "channel": chan, "kind": p.stem}
    for p in sorted((ROOT / "results/relay/calibration").glob("*.json")):
        entries[str(p.relative_to(ROOT))] = {
            "sha256": sha256(p), "channel": "calibration", "kind": "calibration"}
    return entries


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True).stdout.strip()
    except Exception:
        return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="deliberately (re-)pin the manifest")
    args = ap.parse_args()
    current = collect()
    if args.write:
        seeds_seen: dict[tuple, str] = {}
        for rel, e in current.items():
            if "seed" in e and e.get("prompt_version"):
                variant = next((tag for tag in ("long", "numrow", "nocoach")
                                if f"-{tag}-" in rel), "std")
                key = (e["model"], e["condition"], variant, e["budget"], e["seed"],
                       e["prompt_version"], e["channel"])
                if key in seeds_seen:
                    print(f"WARN duplicate cell/seed: {rel} vs {seeds_seen[key]} "
                          "(loader resolves latest-wins; both pinned)")
                seeds_seen[key] = rel
        MANIFEST.write_text(json.dumps(
            {"generator_commit": git_commit(), "n_entries": len(current),
             "entries": current}, indent=1, sort_keys=True))
        print(f"pinned {len(current)} evidence files -> {MANIFEST.relative_to(ROOT)}")
        return 0
    if not MANIFEST.exists():
        print("FAIL: no MANIFEST.json — evidence selection is not pinned "
              "(run --write deliberately)")
        return 1
    pinned = json.loads(MANIFEST.read_text())["entries"]
    missing = sorted(set(pinned) - set(current))
    added = sorted(set(current) - set(pinned))
    changed = sorted(k for k in set(pinned) & set(current)
                     if pinned[k]["sha256"] != current[k]["sha256"])
    if missing or added or changed:
        for k in missing[:5]:
            print(f"FAIL missing: {k}")
        for k in added[:5]:
            print(f"FAIL unpinned addition: {k}")
        for k in changed[:5]:
            print(f"FAIL content drift: {k}")
        print(f"FAIL: manifest mismatch (missing={len(missing)} "
              f"added={len(added)} changed={len(changed)})")
        return 1
    print(f"OK: {len(current)} evidence files match the pinned manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
