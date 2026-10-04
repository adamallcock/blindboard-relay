#!/usr/bin/env python3
"""Release-readiness gates for the Relay paper (obviousbench convention):
each gate is CHECKED against artifacts at generation time, never asserted.
Gates are declared here; evaluation and rendering are delegated to the
vendored benchkit gates framework (scripts/gates_kit.py).
Writes paper/tables/relay_gates.tex."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_vendored import check_consumer  # vendored benchkit self-check
from gates_kit import GateSpec, all_pass, evaluate_gates, print_gates, render_gates_tex

ROOT = Path(__file__).resolve().parents[1]
CAL_V2 = ROOT / "results/relay/calibration/calibration-codecv2.json"


def gate_test_suite() -> tuple[bool, str]:
    proc = subprocess.run(
        ["uv", "run", "--with", "pytest", "-m", "pytest", "-q", "tests/"],
        cwd=ROOT, capture_output=True, text=True, timeout=1800,
    )
    passed = proc.returncode == 0 and "passed" in proc.stdout and "failed" not in proc.stdout
    tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "no output"
    if proc.returncode != 0:
        tail = f"exit {proc.returncode}: {tail}; {proc.stderr.strip()}"
    return passed, tail


def gate_codec_soundness() -> tuple[bool, str]:
    proc = subprocess.run(
        ["uv", "run", "--with", "pytest", "-m", "pytest", "-q",
         "tests/test_relay.py::test_truncation_is_sound_and_parseable",
         "tests/test_relay.py::test_codec_v2_positional_mode"],
        cwd=ROOT, capture_output=True, text=True, timeout=600,
    )
    passed = proc.returncode == 0 and "2 passed" in proc.stdout and "failed" not in proc.stdout
    detail = "sound truncation + positional mode property tests"
    if proc.returncode != 0:
        detail = f"exit {proc.returncode}: {proc.stdout.strip()}; {proc.stderr.strip()}"
    return passed, detail


def gate_certificate() -> tuple[bool, str]:
    """Every archived calibration the paper cites must reproduce on
    recomputation (the reference is deterministic; drift means a stale
    artifact or a determinism regression). Coverage: codec v2 at ALL 40
    seeds for the contested budgets (50, 30); codec v1 spot-checked (the
    .946 disclosure); the 39-key transfer base spot-checked at B=100."""
    from relay.runner import run_relay_reference
    from relay.tiers import BASES, RELAY_BASE, RelayConfig

    def check(cal_path, base, budgets, seeds, positional, label):
        if not cal_path.exists():
            return f"{label}: artifact missing ({cal_path.name})"
        cal = json.loads(cal_path.read_text())
        if not cal.get("deterministic"):
            return f"{label}: artifact not marked deterministic"
        for budget in budgets:
            stored = cal["table"].get(f"budget_{budget}", {}).get("per_seed") or {}
            if not stored:
                return f"{label}: no per-seed floors at B={budget}"
            for seed in seeds:
                fresh = run_relay_reference(
                    RelayConfig(base=base, budget_chars=budget), seed,
                    codec_positional=positional,
                )["board_accuracy"]
                # Artifacts store 6-decimal floors; scores are quantized at
                # 1/n (~.038 or .026), so 1e-5 separates rounding from drift.
                if abs(fresh - float(stored[str(seed)])) > 1e-5:
                    return (f"{label} B={budget} seed {seed}: recompute "
                            f"{fresh:.6f} != archived {float(stored[str(seed)]):.6f}")
        return None

    cal_dir = CAL_V2.parent
    for err in (
        check(CAL_V2, RELAY_BASE, (50, 30), range(40), True, "codec-v2"),
        check(cal_dir / "calibration-codecv1.json", RELAY_BASE, (50, 30),
              range(40), False, "codec-v1"),
        check(cal_dir / "calibration-codecv2-numrow.json", BASES["numrow"],
              (100,), range(40), True, "39-key"),
    ):
        if err:
            return False, err
    # Stored aggregates must equal their own per-seed maps.
    for name in ("calibration-codecv2.json", "calibration-codecv1.json",
                 "calibration-codecv2-numrow.json"):
        cal_x = json.loads((cal_dir / name).read_text())
        for key, cell in cal_x["table"].items():
            per = cell.get("per_seed")
            if per and abs(sum(map(float, per.values())) / len(per)
                           - cell["board_accuracy_mean"]) > 1e-4:
                return False, f"{name} {key}: stored mean != per-seed mean" 
    cal = json.loads(CAL_V2.read_text())
    m50 = cal["table"]["budget_50"]["board_accuracy_mean"]
    m30 = cal["table"]["budget_30"]["board_accuracy_mean"]
    return True, (
        f"v2 floors reproduce at all 40 seeds (B=50 {m50:.3f}, B=30 {m30:.3f}); "
        "v1 and 39-key artifacts verified at all 40 seeds; stored aggregates re-derived"
    )


def gate_prompt_version() -> tuple[bool, str]:
    """Printed cells contain exactly one prompt version BY CONSTRUCTION:
    the loader refuses unstamped episodes. This gate runs the actual
    loader, then independently scans every stored episode file so the
    refused population is visible, not silently exempt."""
    from relay_analysis import load_cells

    cells, refused = load_cells("relay-v2")
    loaded = sum(len(v) for v in cells.values())
    versions = set()
    for seeds in cells.values():
        for r in seeds.values():
            versions.add(r.get("prompt_version"))
    audit_cells, _ = load_cells("relay-v3-nocoach")
    audited = sum(len(v) for v in audit_cells.values())
    legacy = refused - audited  # the v2 loader's refusals include nocoach cells
    # Independent direct scan: OPEN every stored episode file, both channels,
    # and count stamps without the loader (the gate must prove it looked).
    direct = {"llm_v2": 0, "llm_nocoach": 0, "llm_unstamped": 0,
              "svg_v2": 0, "svg_other": 0}
    for chan, root in (("llm", ROOT / "results/relay/llm"),
                       ("svg", ROOT / "results/relay/svg")):
        for d in root.iterdir():
            if not d.is_dir():
                continue
            for p in d.glob("seed*.json"):
                pv = json.loads(p.read_text())["result"].get("prompt_version")
                if chan == "llm":
                    key = ("llm_v2" if pv == "relay-v2" else
                           "llm_nocoach" if pv == "relay-v3-nocoach" else "llm_unstamped")
                else:
                    key = "svg_v2" if pv == "relay-v2" else "svg_other"
                direct[key] += 1
    ok = (
        versions == {"relay-v2"} and loaded > 0
        and direct["llm_v2"] == loaded
        and direct["llm_nocoach"] == audited
        and direct["llm_unstamped"] == legacy
        and direct["svg_other"] == 0
    )
    return ok, (
        f"direct file scan (both channels): {direct['llm_v2']} text + "
        f"{direct['svg_v2']} pixel episodes stamped relay-v2, {direct['llm_unstamped']} "
        f"legacy refused, {direct['llm_nocoach']} nocoach audit episodes (4 cells); "
        f"loader counts match the scan"
    )


def gate_baton_corpus() -> tuple[bool, str]:
    missing = 0
    total = 0
    for d in (ROOT / "results/relay/llm").iterdir():
        for p in d.glob("seed*.json"):
            data = json.loads(p.read_text())
            r = data["result"]
            # Full-transcript (R1) controls are not relay episodes: no
            # baton exists by design, so no turn log is expected.
            if str(r.get("budget")) in ("full", "retained"):
                continue
            if r.get("condition") in ("freeform", "schema", "constitution", "form"):
                total += 1
                if "turns" not in data:
                    missing += 1
    return missing == 0, f"{total} relay episodes, {missing} missing turn logs"


def gate_renderer_determinism() -> tuple[bool, str]:
    from relay.svg_channel import active_renderer, render_svg, sanitize_svg

    renderer = active_renderer()
    if not renderer:
        return False, "no rasterizer available"
    svg = sanitize_svg('<svg width="64" height="64"><text x="4" y="30">GATE</text></svg>')
    a, b = render_svg(svg), render_svg(svg)
    if not a or not b or not a.startswith(b"\x89PNG"):
        return False, f"renderer={renderer}: rendering produced no valid PNG bytes"
    return a == b, f"renderer={renderer}; identical source -> identical PNG bytes"


RENDERER_PROVENANCE = ROOT / "results/relay/calibration/renderer-provenance.json"


def _macos_version() -> str:
    try:
        return subprocess.run(["sw_vers", "-productVersion"], capture_output=True,
                              text=True, timeout=30).stdout.strip()
    except Exception:
        return "unknown"


def _snapshot_pairs():
    pairs = []
    for d in sorted((ROOT / "results/relay/svg").iterdir()):
        if not d.is_dir():
            continue
        for svg_p in sorted(d.glob("*.svg")):
            pairs.append((svg_p, svg_p.with_suffix(".png")))
    return pairs


def _renderer_host_matches() -> bool:
    """True when this host runs the macOS version the snapshot renders were
    verified on — the only host where a byte-match check is meaningful.
    A missing or unreadable provenance record counts as a match, so the
    gate stays REQUIRED (and fails) rather than being waived."""
    try:
        rec = json.loads(RENDERER_PROVENANCE.read_text())
        return rec["verified_macos_version"] == _macos_version()
    except Exception:
        return True


def gate_snapshot_renderer_provenance() -> tuple[bool, str]:
    """Snapshot pixel-channel provenance. The stored PNGs are the channel
    record (covered by the release bundle's complete checksum inventory,
    separately from the experiment manifest). On the macOS version the
    renders were verified on, every stored SVG must re-render byte-for-byte
    with qlmanage. On any other version Quick Look's rasterizer may differ, so
    the check cannot be re-run: the gate reports that plainly (the spec is
    then non-required, i.e. a visible WAIVED, never a silent pass)."""
    import os

    from relay.svg_channel import render_svg

    if not RENDERER_PROVENANCE.exists():
        return False, "renderer provenance record missing (results/relay/calibration/renderer-provenance.json)"
    rec = json.loads(RENDERER_PROVENANCE.read_text())
    pairs = _snapshot_pairs()
    if not pairs:
        return False, "no stored svg/png pairs found"
    missing = [s for s, p in pairs if not p.exists()]
    if missing:
        return False, f"missing PNG counterpart for {missing[0].parent.name}/{missing[0].name}"
    if len(pairs) != rec.get("pairs_verified"):
        return False, (f"{len(pairs)} stored pairs but provenance record verified "
                       f"{rec.get('pairs_verified')}")
    host = _macos_version()
    if host != rec["verified_macos_version"]:
        return False, (
            f"not re-verifiable on macOS {host}: snapshot verified byte-exact on macOS "
            f"{rec['verified_macos_version']} ({rec['pairs_verified']} pairs, "
            f"{rec['verified_on']}); verify stored PNG integrity against bundle SHA256SUMS"
        )
    prev = os.environ.get("RELAY_RENDERER")
    os.environ["RELAY_RENDERER"] = "qlmanage"
    try:
        for svg_p, png_p in pairs:
            png = render_svg(svg_p.read_text())
            if not png:
                return False, f"qlmanage produced no render for {svg_p.parent.name}/{svg_p.name}"
            if png != png_p.read_bytes():
                return False, f"byte mismatch: {svg_p.parent.name}/{svg_p.name}"
    finally:
        if prev is None:
            os.environ.pop("RELAY_RENDERER", None)
        else:
            os.environ["RELAY_RENDERER"] = prev
    return True, (
        f"all {len(pairs)} stored svg/png pairs byte-match qlmanage on macOS {host}"
    )


def gate_vendored_drift() -> tuple[bool, str]:
    report = check_consumer(ROOT)
    return report.ok, report.summary()


def gate_evidence_manifest() -> tuple[bool, str]:
    """The evidence selection is pinned: every stored episode, probe,
    summary, and calibration file must hash-match results/relay/MANIFEST.json
    (fail closed on missing manifest, drift, additions, or removals)."""
    proc = subprocess.run(
        [sys.executable, "scripts/relay_manifest.py"],
        cwd=ROOT, capture_output=True, text=True, timeout=600,
    )
    tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "no output"
    return proc.returncode == 0, tail


SPECS = [
    GateSpec("test suite", gate_test_suite),
    GateSpec("codec soundness (every cut point)", gate_codec_soundness),
    GateSpec("calibration artifact reproduces (deterministic floors)", gate_certificate),
    GateSpec("prompt version (loader refuses unstamped episodes)", gate_prompt_version),
    GateSpec("baton corpus stored verbatim", gate_baton_corpus),
    GateSpec("SVG renderer determinism (shipped default)", gate_renderer_determinism),
    # Required only on the macOS version the renders were verified on; on any
    # other version the gate reports WAIVED (visible) instead of passing.
    GateSpec("snapshot renderer provenance (qlmanage byte-match)",
             gate_snapshot_renderer_provenance,
             profiles=None if _renderer_host_matches() else ("renderer-verification-host",)),
    GateSpec("vendored infrastructure drift (benchkit)", gate_vendored_drift),
    GateSpec("evidence manifest (selection pinned, fail-closed)", gate_evidence_manifest),
]


def main() -> int:
    results = evaluate_gates(SPECS)
    (ROOT / "paper/tables").mkdir(parents=True, exist_ok=True)
    (ROOT / "paper/tables/relay_gates.tex").write_text(
        render_gates_tex(results, generator="scripts/relay_gates.py")
    )
    print_gates(results)
    # Fail closed: any failing gate must fail the process, or `make
    # relay-check` succeeds on a failing release.
    return 0 if all_pass(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
