#!/usr/bin/env python3
"""Fixed-codec reference negative control for the drift metric.

Twenty deterministic reference chains per budget share ONE codec/convention
by construction. If their cross-chain skeleton similarity also falls
late-vs-early, a falling between-chain curve cannot discriminate
chain-specific convention formation from state-shape divergence — which is
exactly what the uncertainty review demonstrated. This script archives that
control as a generated artifact (deterministic, reproducible), so the paper
cites a pinned number rather than an ad-hoc run.

  uv run python scripts/relay_negative_control.py
"""

from __future__ import annotations

import json
import sys
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from blindboard.env import Episode
from relay.agents import MemoReferenceAgent
from relay.tiers import RELAY_BASE_LONG, RelayConfig
from relay_analysis import skeleton

OUT = Path(__file__).resolve().parents[1] / "results/relay/calibration/negative-control.json"
N_CHAINS = 20


def chains_for(budget: int) -> list[list[str]]:
    out = []
    for seed in range(N_CHAINS):
        cfg = RelayConfig(base=RELAY_BASE_LONG, budget_chars=budget)
        ep = Episode(cfg.base, seed)
        ag = MemoReferenceAgent(cfg, seed)
        batons = []
        while not ep.done:
            action, memo = ag.relay_act(ep.observation())
            err = ep.validate(action)
            if err:
                raise RuntimeError(f"reference illegal action: {err}")
            ep.apply(action)
            if memo:
                batons.append(memo)
        out.append(batons)
    return out


def cross_chain(chains: list[list[str]], lo=None, hi=None) -> float | None:
    sims = []
    max_gen = max(len(c) for c in chains)
    for g in range(max_gen):
        if lo is not None and g < lo:
            continue
        if hi is not None and g > hi:
            continue
        notes = [c[g] for c in chains if g < len(c)]
        for i in range(len(notes)):
            for j in range(i + 1, len(notes)):
                sims.append(SequenceMatcher(
                    None, skeleton(notes[i]), skeleton(notes[j])).ratio())
    return sum(sims) / len(sims) if sims else None


def main() -> None:
    table = {}
    for budget in (100, 200):
        chains = chains_for(budget)
        early = cross_chain(chains, hi=6)
        late = cross_chain(chains, lo=12)
        table[f"budget_{budget}"] = {
            "n_chains": N_CHAINS,
            "cross_chain_early": round(early, 6),
            "cross_chain_late": round(late, 6),
            "late_minus_early": round(late - early, 6),
        }
        print(f"B={budget}: reference cross-chain early={early:.3f} "
              f"late={late:.3f} delta={late-early:+.3f}")
    OUT.write_text(json.dumps(
        {"deterministic": True, "base": "long", "metric": "skeleton-SequenceMatcher",
         "note": "fixed-codec reference chains share one convention by construction; "
                 "a late fall here means the between-chain metric is "
                 "state-shape-sensitive, not convention-discriminating",
         "table": table}, indent=1, sort_keys=True))
    print(f"saved {OUT}")


if __name__ == "__main__":
    main()
