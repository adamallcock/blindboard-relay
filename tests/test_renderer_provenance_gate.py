"""The snapshot renderer-provenance gate must never pass silently: a missing
record fails (and stays required); a different macOS version reports
not-re-verifiable (and is waived, visibly); on the verified version any byte
mismatch fails."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import relay_gates  # noqa: E402


def _setup(tmp_path, monkeypatch, *, version="26.5.2", record=True, n_pairs=1):
    pairs = []
    for i in range(n_pairs):
        svg = tmp_path / f"p{i}.svg"
        svg.write_text("<svg/>")
        png = tmp_path / f"p{i}.png"
        png.write_bytes(b"\x89PNGstored")
        pairs.append((svg, png))
    rec_path = tmp_path / "renderer-provenance.json"
    if record:
        rec_path.write_text(json.dumps({
            "verified_macos_version": "26.5.2", "verified_on": "2026-07-28",
            "pairs_verified": 1}))
    monkeypatch.setattr(relay_gates, "RENDERER_PROVENANCE", rec_path)
    monkeypatch.setattr(relay_gates, "_snapshot_pairs", lambda: pairs)
    monkeypatch.setattr(relay_gates, "_macos_version", lambda: version)


def test_missing_record_fails_and_stays_required(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, record=False)
    assert relay_gates._renderer_host_matches() is True  # required, not waived
    ok, summary = relay_gates.gate_snapshot_renderer_provenance()
    assert not ok and "missing" in summary


def test_other_macos_version_is_not_reverifiable(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, version="26.6.2")
    assert relay_gates._renderer_host_matches() is False  # waived, visibly
    ok, summary = relay_gates.gate_snapshot_renderer_provenance()
    assert not ok and "not re-verifiable" in summary


def test_pair_count_mismatch_fails(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, n_pairs=2)
    ok, summary = relay_gates.gate_snapshot_renderer_provenance()
    assert not ok and "provenance record verified" in summary


def test_verified_host_byte_match_and_mismatch(tmp_path, monkeypatch):
    import relay.svg_channel as svg_channel

    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(svg_channel, "render_svg", lambda s: b"\x89PNGstored")
    assert relay_gates.gate_snapshot_renderer_provenance()[0] is True
    monkeypatch.setattr(svg_channel, "render_svg", lambda s: b"\x89PNGdifferent")
    ok, summary = relay_gates.gate_snapshot_renderer_provenance()
    assert not ok and "byte mismatch" in summary
