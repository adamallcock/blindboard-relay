"""Bibliography and redline failures must preserve the last usable inputs."""

import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def stub(directory, name, body):
    path = directory / name
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(0o755)


def run_make(tmp_path, target, executable, body):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub(bin_dir, executable, body)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", TMPDIR=str(tmp_path))
    return subprocess.run(
        ["make", "-f", str(ROOT / "paper/Makefile"), f"ROOT={ROOT}", target],
        cwd=tmp_path, env=env, capture_output=True, text=True,
    )


@pytest.mark.parametrize("compiler_exit", [0, 1])
def test_bbl_missing_or_failed_build_preserves_previous_file(tmp_path, compiler_exit):
    previous = b"previous bibliography\n"
    (tmp_path / "relay.bbl").write_bytes(previous)
    result = run_make(tmp_path, "relay-bbl", "tectonic", f"exit {compiler_exit}")
    assert result.returncode != 0
    assert "relay-bbl: wrote" not in result.stdout
    assert (tmp_path / "relay.bbl").read_bytes() == previous
    assert sorted(p.name for p in tmp_path.iterdir()) == ["bin", "relay.bbl"]


def test_failed_redline_restores_held_bibliography(tmp_path):
    previous = b"previous bibliography\n"
    (tmp_path / "relay.bbl").write_bytes(previous)
    result = run_make(tmp_path, "relay-redline", "latexdiff", "exit 1")
    assert result.returncode != 0
    assert (tmp_path / "relay.bbl").read_bytes() == previous
    assert sorted(p.name for p in tmp_path.iterdir()) == ["bin", "relay.bbl"]
