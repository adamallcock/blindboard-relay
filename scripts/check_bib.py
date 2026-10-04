#!/usr/bin/env python3
"""Bib gate adapter (house rule: every consumer routes bib verification
through check_bib.py). Since benchkit@0.1.5 (kit commit 7ca1c83) the
vendored verify_bib parses multi-line entries natively and fails loudly
when a bib with eprint fields yields zero parsed entries, so this adapter
only (a) invokes it, (b) re-asserts at the consumer level that the gate
actually looked (nonzero entries when eprints exist), and (c) returns a
real exit code for the Makefile."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bib", default=str(SCRIPTS.parent / "paper" / "references.bib"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    bib_text = Path(args.bib).read_text(encoding="utf-8")
    eprints = bib_text.count("eprint")
    cmd = [sys.executable, str(SCRIPTS / "verify_bib.py"), "--bib", args.bib]
    if args.apply:
        cmd.append("--apply")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)

    match = re.search(r"(\d+) arXiv entries", proc.stdout)
    seen = int(match.group(1)) if match else 0
    if eprints and seen == 0:
        print(
            f"FAIL: bib has {eprints} eprint field(s) but verify_bib saw none -- "
            "the gate did not look; bib verification is not running."
        )
        return 2
    if proc.returncode != 0:
        return proc.returncode
    print(f"check_bib: OK ({seen} entries verified against arXiv)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
