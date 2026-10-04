"""Relay's retained-reasoning controls: the cost the harness recorded for each
episode equals every call re-priced at its collection day's list price
(cache classes included), so no retained episode is priced at a stale era."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
LLM = ROOT / "results/relay/llm"


def _retained_episodes() -> list[Path]:
    if not LLM.exists():
        return []
    return [p for d in sorted(LLM.iterdir()) if "-bretained-" in d.name
            for p in sorted(d.glob("seed*.json"))]


@pytest.mark.skipif(not _retained_episodes(), reason="relay evidence is local-only")
def test_retained_costs_match_dated_repricing() -> None:
    import relay_analysis as ra

    mismatches = []
    for path in _retained_episodes():
        data = json.loads(path.read_text())
        result = data["result"]
        repriced = ra._dated_episode_cost({"transcript": data.get("transcript", [])},
                                          result.get("model") or "", path.parent.name)
        recorded = result.get("cost_usd_list")
        if recorded is None or repriced is None or abs(recorded - repriced) > 1e-9:
            mismatches.append((path.parent.name, path.name, recorded, repriced))
    assert not mismatches, mismatches[:5]
