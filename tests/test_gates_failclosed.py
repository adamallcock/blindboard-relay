"""The gates runner must fail the PROCESS when a required gate fails —
a printed FAIL with exit 0 lets `make relay-check` bless a broken release."""
import sys
import subprocess
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_main_returns_nonzero_on_planted_failure(monkeypatch, tmp_path):
    import relay_gates
    from gates_kit import GateSpec

    monkeypatch.setattr(relay_gates, "ROOT", tmp_path)  # tables write to scratch
    (tmp_path / "paper/tables").mkdir(parents=True)
    monkeypatch.setattr(relay_gates, "SPECS", [
        GateSpec("planted pass", lambda: (True, "ok")),
        GateSpec("planted failure", lambda: (False, "forced")),
    ])
    assert relay_gates.main() == 1


def test_main_returns_zero_when_all_pass(monkeypatch, tmp_path):
    import relay_gates
    from gates_kit import GateSpec

    monkeypatch.setattr(relay_gates, "ROOT", tmp_path)
    (tmp_path / "paper/tables").mkdir(parents=True)
    monkeypatch.setattr(relay_gates, "SPECS", [
        GateSpec("planted pass", lambda: (True, "ok")),
    ])
    assert relay_gates.main() == 0


@pytest.mark.parametrize("gate,summary", [
    ("gate_test_suite", "309 passed in 1s"),
    ("gate_codec_soundness", "2 passed in 1s"),
])
def test_pass_text_cannot_override_failed_process(monkeypatch, gate, summary):
    import relay_gates
    monkeypatch.setattr(relay_gates.subprocess, "run", lambda *a, **k:
                        subprocess.CompletedProcess([], 2, summary, "fatal error"))
    passed, detail = getattr(relay_gates, gate)()
    assert not passed
    assert "exit 2" in detail
    assert "fatal error" in detail
