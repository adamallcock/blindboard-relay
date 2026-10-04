#!/usr/bin/env python3
"""SVG-channel campaign: game episodes + the transcription probe.

  secret run copybench-openai --env OPENAI_API_KEY -- \
    uv run python scripts/relay_svg_run.py --model gpt-5.6-luna --seeds 10 --probe-pairs 12

The transcription probe isolates channel fidelity from game skill:
instance A gets a random partial board state as TEXT and must draw it as
SVG; a fresh instance B sees ONLY the rendering and must read the state
back. Recovery precision/recall is the write->render->read loss floor."""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from blindboard.boards import BOARDS
from blindboard.client import Message
from blindboard.protocol import extract_json
from blindboard.runner import summarize
from relay.runner import run_relay_svg
from relay.svg_channel import MAX_SVG_BYTES, png_b64, render_svg, sanitize_svg
from relay.tiers import RELAY_BASE, RelayConfig
from relay.vision import VisionAdapter

BOARD = BOARDS["qwerty26"]

WRITE_PROMPT = (
    "Encode this keyboard knowledge as a self-contained SVG image (max {mb} bytes; "
    "shapes and text only). A fresh instance of you will see ONLY the rendered "
    "512x512 image and must recover every fact. The facts: {facts}. "
    'Reply with ONLY JSON: {{"svg": "<svg...>"}}'
)

READ_PROMPT = (
    "The attached image was drawn by you to encode keyboard knowledge: which keys "
    "hold which symbols. Keys are named like L-pinky-top, R-index-home-in. Read "
    'the image and reply with ONLY JSON: {{"known": {{"<address>": "<SYMBOL>", ...}}}}. '
    "Include exactly the facts you can read."
)


def probe_pair(adapter: VisionAdapter, seed: int, out_dir: Path) -> dict:
    rng = random.Random(f"probe:{seed}")
    layout = list(BOARD.symbols)
    rng.shuffle(layout)
    positions = rng.sample(range(BOARD.n), 10)
    truth = {BOARD.addresses[p]: layout[p] for p in positions}
    facts = "; ".join(f"{a} = {s}" for a, s in truth.items())
    write_reply, _ = adapter.call_with_image(
        [Message("user", WRITE_PROMPT.format(mb=MAX_SVG_BYTES, facts=facts))], None
    )
    data = extract_json(write_reply)
    svg = sanitize_svg(data.get("svg", "")) if isinstance(data, dict) else None
    row = {"seed": seed, "truth": truth, "svg_ok": svg is not None,
           "recovered": {}, "precision": 0.0, "recall": 0.0}
    if svg is None:
        return row
    png = render_svg(svg)
    if png is None:
        row["svg_ok"] = False
        return row
    (out_dir / f"probe{seed:03d}.svg").write_text(svg)
    (out_dir / f"probe{seed:03d}.png").write_bytes(png)
    read_reply, _ = adapter.call_with_image([Message("user", READ_PROMPT)], png_b64(png))
    rdata = extract_json(read_reply)
    recovered = rdata.get("known", {}) if isinstance(rdata, dict) else {}
    lookup = {a.lower(): a for a in BOARD.addresses}
    clean = {}
    for k, v in (recovered.items() if isinstance(recovered, dict) else []):
        addr = lookup.get(str(k).strip().lower().replace("_", "-").replace(" ", "-"))
        if addr and isinstance(v, str):
            clean[addr] = v.strip().upper()
    hits = sum(1 for a, s in clean.items() if truth.get(a) == s)
    row["recovered"] = clean
    row["precision"] = hits / len(clean) if clean else 0.0
    row["recall"] = hits / len(truth)
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--seeds", type=int, default=10, help="game episodes")
    parser.add_argument("--probe-pairs", type=int, default=12)
    parser.add_argument("--effort", default="medium")
    parser.add_argument("--service-tier", default="flex")
    parser.add_argument("--parallel", type=int, default=8)
    parser.add_argument("--out", default="results/relay/svg")
    args = parser.parse_args()

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out) / f"{args.model}-{args.effort}-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) Transcription probe (channel fidelity floor).
    def one_pair(seed: int) -> dict:
        adapter = VisionAdapter(model=args.model, effort=args.effort,
                                service_tier=args.service_tier or None)
        row = probe_pair(adapter, seed, out_dir)
        print(f"probe {seed}: svg_ok={row['svg_ok']} recall={row['recall']:.2f} "
              f"precision={row['precision']:.2f}", flush=True)
        return row

    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        probe_rows = list(pool.map(one_pair, range(args.probe_pairs)))
    probe_summary = {
        "pairs": len(probe_rows),
        "svg_ok_rate": sum(r["svg_ok"] for r in probe_rows) / len(probe_rows),
        "recall_mean": sum(r["recall"] for r in probe_rows) / len(probe_rows),
        "precision_mean": sum(r["precision"] for r in probe_rows) / len(probe_rows),
    }
    (out_dir / "probe.json").write_text(json.dumps(
        {"summary": probe_summary, "rows": probe_rows}, indent=1, sort_keys=True))
    print("PROBE:", json.dumps(probe_summary), flush=True)

    # 2) Game episodes through the pixel channel.
    config = RelayConfig(base=RELAY_BASE, condition="svg")

    def one_episode(seed: int) -> dict:
        adapter = VisionAdapter(model=args.model, effort=args.effort,
                                service_tier=args.service_tier or None)
        t0 = time.time()
        result = run_relay_svg(adapter, config, seed, transcript_dir=out_dir)
        print(f"seed {seed}: correct {result['correct']}/{result['board_n']} "
              f"svg={result['svg_stats']} ({time.time() - t0:.0f}s)", flush=True)
        return result

    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        results = list(pool.map(one_episode, range(args.seeds)))
    summary = summarize(results)
    summary["model"] = args.model
    summary["effort"] = args.effort
    summary["condition"] = "svg"
    summary["budget"] = "svg512"
    summary["probe"] = probe_summary
    svg_totals = {}
    for r in results:
        for k, v in r["svg_stats"].items():
            svg_totals[k] = svg_totals.get(k, 0) + v
    summary["svg_stats_total"] = svg_totals
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True))
    print(json.dumps(summary, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
