#!/usr/bin/env python3
"""Aggregate relay runs into the support-ladder matrix:
rows = (model, condition), columns = budgets, cells = mean accuracy (n).

  uv run python scripts/relay_report.py [--prompt-version relay-v2]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BUDGET_ORDER = ["full", "800", "200", "100", "75", "50", "30", "25", "vanishing"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", default="results/relay/llm")
    parser.add_argument("--prompt-version", default=None,
                        help="filter episodes to a prompt version (e.g. relay-v2); default all")
    args = parser.parse_args()

    cells: dict[tuple[str, str, str], dict[int, float]] = defaultdict(dict)
    for run_dir in sorted(Path(args.results).iterdir()):
        sp = run_dir / "summary.json"
        if not sp.exists():
            continue
        s = json.loads(sp.read_text())
        condition = s.get("condition", "freeform")
        # Base inferred from dirname tag (-long-/-numrow-); std otherwise.
        for tag in ("long", "numrow"):
            if f"-{tag}-" in run_dir.name:
                condition = f"{condition}@{tag}"
        budget = str(s.get("budget"))
        for ep_path in sorted(run_dir.glob("seed*.json")):
            r = json.loads(ep_path.read_text())["result"]
            if args.prompt_version and r.get("prompt_version") != args.prompt_version:
                # R1 controls carry no prompt_version; keep them.
                if budget != "full":
                    continue
            cells[(s["model"], condition, budget)][r["seed"]] = r["board_accuracy"]

    keys = sorted({(m, c) for m, c, _ in cells})
    budgets = [b for b in BUDGET_ORDER if any((m, c, b) in cells for m, c in keys)]
    header = ["model", "condition"] + budgets
    print("| " + " | ".join(header) + " |")
    print("|" + "|".join("---" for _ in header) + "|")
    for model, condition in keys:
        row = [model.replace("gpt-5.", ""), condition]
        for b in budgets:
            seeds = cells.get((model, condition, b))
            if not seeds:
                row.append("–")
            else:
                accs = list(seeds.values())
                row.append(f"{sum(accs)/len(accs):.3f} ({len(accs)})")
        print("| " + " | ".join(row) + " |")


if __name__ == "__main__":
    main()
