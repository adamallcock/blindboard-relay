#!/usr/bin/env python3
"""Run an LLM on the relay track (fresh context per turn, baton memory).

  secret run copybench-openai --env OPENAI_API_KEY -- \
    uv run python scripts/relay_run.py --model gpt-5.6-luna --budgets 800 200 50 --seeds 5

--budgets full      = visible-transcript control (legacy text adapters; now fails
                      closed, kept so old cells stay reproducible in principle).
--budgets retained  = retained-reasoning control: same full transcript, driven by
                      blindboard.retained_adapter (every native output item,
                      encrypted reasoning included, replayed each turn).
--vanishing    = the shrinking-notepad schedule instead of constant budgets.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from blindboard.anthropic_client import make_adapter
from blindboard.llm_runner import run_llm_episode
from blindboard.retained_adapter import HARNESS as RETAINED_HARNESS, RetainedReasoningAdapter
from blindboard.runner import summarize
from relay.prompts import prompt_version_for
from relay.runner import run_relay_llm
from relay.tiers import BASES, VANISHING, RelayConfig


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--budgets", nargs="*", default=["800", "400", "200", "100", "50"],
                        help="character budgets; 'full' = visible-transcript control; "
                             "'retained' = retained-reasoning control")
    parser.add_argument("--vanishing", action="store_true")
    parser.add_argument("--condition", default="freeform",
                        choices=["freeform", "schema", "constitution", "form"])
    parser.add_argument("--base", default="std", choices=["std", "long", "numrow"])
    parser.add_argument("--prompt-variant", default="v2", choices=["v2", "nocoach"],
                        help="'nocoach' = v2 rules minus the coaching sentences (instrument audit)")
    parser.add_argument("--legacy-visible", action="store_true",
                        help="required for --budgets full: reproduce the July "
                             "visible-transcript control (text-only, reasoning discarded) "
                             "for paired replication; stamped as a legacy opt-in")
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--seed-offset", type=int, default=0)
    parser.add_argument("--effort", default="medium")
    parser.add_argument("--service-tier", default="flex")
    parser.add_argument("--parallel", type=int, default=16)
    parser.add_argument("--out", default="results/relay/llm")
    args = parser.parse_args()

    if "full" in (args.budgets or []) and not args.legacy_visible:
        raise SystemExit("--budgets full reproduces the legacy visible-transcript control; "
                         "pass --legacy-visible to confirm, or use --budgets retained")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    cells = [("vanishing", None)] if args.vanishing else [(b, b) for b in args.budgets]
    seeds = list(range(args.seed_offset, args.seed_offset + args.seeds))

    base = BASES[args.base]
    base_tag = "" if args.base == "std" else f"-{args.base}"
    variant_tag = "" if args.prompt_variant == "v2" else f"-{args.prompt_variant}"
    pv = prompt_version_for(args.prompt_variant)
    model_tag = args.model.replace("/", "-")  # provider-prefixed IDs stay one dir level
    for cell_name, budget in cells:
        run_dir = Path(args.out) / (
            f"{model_tag}-{args.effort}-{args.condition}{base_tag}{variant_tag}-b{cell_name}-{stamp}"
        )

        failures: dict[int, str] = {}
        failed_costs: dict[int, float] = {}
        adapters: dict[int, object] = {}

        def run_one(seed: int, budget=budget, run_dir=run_dir) -> dict:
            # Relay turns are single inferences; the only multi-message call is
            # the same-turn correction retry, which replays the rejected reply
            # as text. That is the published relay-v2 protocol, so relay cells
            # opt in to it explicitly (each reply's meta records
            # conversation_state). The full-transcript runner still refuses a
            # text-only adapter regardless of this flag.
            if budget == "retained":
                adapter = RetainedReasoningAdapter(model=args.model, effort=args.effort,
                                                   service_tier=args.service_tier or None)
            else:
                # Note cells: the lossy opt-in covers only the same-turn retry.
                # Legacy visible control: the runner's double opt-in needs it too.
                adapter = make_adapter(model=args.model, effort=args.effort,
                                       service_tier=args.service_tier or None,
                                       allow_lossy_multi_turn=True)
            adapters[seed] = adapter
            t0 = time.time()
            if budget in ("full", "retained"):
                result = run_llm_episode(adapter, base, seed, transcript_dir=run_dir,
                                         legacy_visible_transcript=budget == "full")
                # R1 controls carry the same stamps as relay cells so the
                # analysis loader (which refuses unstamped episodes) can
                # pair against them.
                # Keep the base game's own prompt stamp; relay's goes alongside.
                result["base_prompt_version"] = result.get("prompt_version")
                result["condition"] = "freeform"
                result["prompt_version"] = pv
                result["harness"] = result.get("harness") or (
                    RETAINED_HARNESS if budget == "retained" else "visible-transcript")
                if budget == "retained":
                    result["reasoning_context"] = "all_turns"
                    result["cost_usd_list"] = adapter.cost_usd()
            elif budget is None:
                result = run_relay_llm(adapter, VANISHING, seed, transcript_dir=run_dir)
            else:
                config = RelayConfig(base=base, budget_chars=int(budget),
                                     condition=args.condition,
                                     prompt_variant=args.prompt_variant)
                result = run_relay_llm(adapter, config, seed, transcript_dir=run_dir)
            d = result.get("diagnostics") or {}
            print(
                f"[b={cell_name}] seed {seed}: correct {result['correct']}/{result['board_n']} "
                f"deducible={d.get('deducible_at_guess', '-')} "
                f"no_note={result.get('no_note_turns', '-')} trunc={result.get('truncated_turns', '-')} "
                f"({time.time() - t0:.0f}s)",
                flush=True,
            )
            return result

        def run_guarded(seed: int):
            # One failed seed must not erase a cell: record it and move on, so
            # the summary is written and the cell's n visibly drops.
            try:
                return run_one(seed)
            except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
                failures[seed] = f"{type(exc).__name__}: {str(exc)[:300]}"
                # A failed attempt is still billed for the calls it completed.
                spent = adapters[seed].cost_usd() if seed in adapters else None
                if spent:
                    failed_costs[seed] = round(spent, 6)
                print(f"[b={cell_name}] seed {seed}: FAILED {failures[seed]}", flush=True)
                return None

        with ThreadPoolExecutor(max_workers=args.parallel) as pool:
            results = [r for r in pool.map(run_guarded, seeds) if r is not None]
        if not results:
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "failed_run.json").write_text(json.dumps(
                {"model": args.model, "budget": cell_name, "condition": args.condition,
                 "failures": {str(k): v for k, v in sorted(failures.items())},
                 "failed_cost_usd_list": {str(k): v for k, v in sorted(failed_costs.items())}},
                indent=1, sort_keys=True), encoding="utf-8")
            raise SystemExit(f"every seed failed in cell {cell_name}: {failures}")
        if cell_name in ("full", "retained"):
            # run_llm_episode wrote the transcripts before we stamped the
            # in-memory results; stamp the stored episodes to match.
            by_seed = {r["seed"]: r for r in results}
            for sp in run_dir.glob("seed*.json"):
                data = json.loads(sp.read_text())
                r = by_seed[data["result"]["seed"]]
                for key in ("base_prompt_version", "condition", "prompt_version",
                            "harness", "reasoning_context", "cost_usd_list"):
                    if key in r:
                        data["result"][key] = r[key]
                data["result"]["budget"] = cell_name
                sp.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True),
                              encoding="utf-8")
        summary = summarize(results)
        summary["model"] = args.model
        summary["effort"] = args.effort
        summary["budget"] = cell_name
        summary["condition"] = args.condition
        summary["prompt_version"] = pv
        if failures:
            summary["failed_seeds"] = sorted(failures)
            summary["failures"] = {str(k): v for k, v in sorted(failures.items())}
        if failed_costs:
            summary["failed_cost_usd_list"] = {str(k): v for k, v in sorted(failed_costs.items())}
        if cell_name in ("full", "retained"):
            summary["harness"] = results[0].get("harness")
            costs = [r.get("cost_usd_list") for r in results]
            if cell_name == "retained" and all(c is not None for c in costs):
                summary["cost_usd_list_price"] = round(sum(costs), 4)
        summary["no_note_turns_total"] = sum(r.get("no_note_turns", 0) for r in results)
        summary["truncated_turns_total"] = sum(r.get("truncated_turns", 0) for r in results)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "summary.json").write_text(
            json.dumps(summary, indent=1, sort_keys=True), encoding="utf-8"
        )
        print(json.dumps(summary, indent=1, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
