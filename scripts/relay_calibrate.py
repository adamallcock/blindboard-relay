#!/usr/bin/env python3
"""Relay certificates: run the budget-matched reference across budgets.

  uv run python scripts/relay_calibrate.py --seeds 40 --codec v2

Writes a stamped artifact AND a canonical `calibration-codec<v>.json` that
the figure script and gates load — floors are never hand-typed downstream.
The reference path is deterministic (hash-seed-independent; sorted set
iteration in the tracker), so these artifacts are exactly reproducible.
--codec v1 re-certifies the pre-positional entry-only codec, archived so
the codec upgrade's effect on the floor is itself on the record."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from blindboard.agents import ReferenceAgent
from blindboard.runner import run_scripted_episode, summarize
from relay.runner import run_relay_reference
from relay.tiers import BASES, RelayConfig


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--budgets", nargs="*", type=int,
                        default=[1200, 800, 400, 200, 100, 75, 50, 30, 25])
    parser.add_argument("--seeds", type=int, default=40)
    parser.add_argument("--codec", default="v2", choices=["v2", "v1"],
                        help="v2 = entry+positional (current); v1 = entry-only (pre-adoption)")
    parser.add_argument("--base", default="std", choices=["std", "numrow"],
                        help="std = 26-key relay base; numrow = 39-key transfer base")
    parser.add_argument("--out", default="results/relay/calibration")
    args = parser.parse_args()
    positional = args.codec == "v2"
    base = BASES[args.base]

    # R1 ceiling on the same base game (unbounded memory).
    r1 = [run_scripted_episode(ReferenceAgent(base, s, samples=30), base, s)
          for s in range(args.seeds)]
    s = summarize(r1)
    s["per_seed"] = {str(i): round(r["board_accuracy"], 6) for i, r in enumerate(r1)}
    print(f"{'R1 reference (full memory)':34s} acc={s['board_accuracy_mean']:.3f} "
          f"solve={s['solve_rate']:.2f}")

    table = {"r1_reference": s}
    for budget in args.budgets:
        config = RelayConfig(base=base, budget_chars=budget)
        results = [run_relay_reference(config, seed, codec_positional=positional)
                   for seed in range(args.seeds)]
        s = summarize(results)
        s["needed_chars_max"] = max(r["needed_chars_max"] for r in results)
        s["per_seed"] = {str(r["seed"]): round(r["board_accuracy"], 6) for r in results}
        table[f"budget_{budget}"] = s
        print(f"{'memo reference @ ' + str(budget):34s} acc={s['board_accuracy_mean']:.3f} "
              f"solve={s['solve_rate']:.2f} peak_needed={s['needed_chars_max']}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    payload = json.dumps(
        {"seeds": args.seeds, "codec": args.codec, "base": args.base, "stamp": stamp,
         "deterministic": True, "table": table},
        indent=1, sort_keys=True,
    )
    tag = "" if args.base == "std" else f"-{args.base}"
    for name in (f"calibration-codec{args.codec}{tag}-{stamp}.json",
                 f"calibration-codec{args.codec}{tag}.json"):
        (out_dir / name).write_text(payload, encoding="utf-8")
        print(f"saved {out_dir}/{name}")


if __name__ == "__main__":
    main()
