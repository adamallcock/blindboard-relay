# Vendored from benchkit@0.3.10 (sha256:c6b1a5a61a5f23d0). Do not hand-edit; run 'benchkit sync' to update.
"""Consumer-side vendored-file self-check (no kit repo required).

This module is itself vendored into consumers so their readiness gates can
verify, fully offline, that no vendored file has been hand-edited since the
last `benchkit sync`:

- every target listed in `.benchkit.json` exists,
- its payload (file minus the vendor header) hashes to the value recorded
  in the manifest at sync time,
- the hash and version stamped in the file's own header agree with both.

Because the manifest hashes and headers are written by the kit at sync
time for the pinned version, a clean pass means "these bytes are exactly
what benchkit@<pinned> rendered". What this check cannot see is whether
the kit has moved on since the pin — run `benchkit check <consumer>` from
the kit repo for that.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

MANIFEST_NAME = ".benchkit.json"


@dataclass(frozen=True)
class VendorFinding:
    target: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class VendorCheckReport:
    pinned_version: str
    findings: tuple[VendorFinding, ...]

    @property
    def ok(self) -> bool:
        return all(finding.ok for finding in self.findings)

    @property
    def checked(self) -> int:
        return len(self.findings)

    def summary(self) -> str:
        bad = [finding for finding in self.findings if not finding.ok]
        if not bad:
            return (
                f"{self.checked} vendored file(s) match benchkit@{self.pinned_version}"
            )
        worst = "; ".join(f"{finding.target}: {finding.detail}" for finding in bad[:3])
        more = f" (+{len(bad) - 3} more)" if len(bad) > 3 else ""
        return f"{len(bad)}/{self.checked} drifted — {worst}{more}"


def _split_header(text: str) -> tuple[str | None, str]:
    lines = text.split("\n")
    for index in (0, 1):
        if index < len(lines) and "Vendored from benchkit@" in lines[index]:
            return lines[index], "\n".join(lines[:index] + lines[index + 1 :])
    return None, text


def _parse_header(header: str) -> tuple[str, str]:
    marker = "Vendored from benchkit@"
    rest = header[header.index(marker) + len(marker) :]
    version = rest.split(" ", 1)[0]
    hash_start = rest.index("sha256:") + len("sha256:")
    return version, rest[hash_start : hash_start + 16]


def check_consumer(consumer_root: Path) -> VendorCheckReport:
    manifest_path = Path(consumer_root) / MANIFEST_NAME
    if not manifest_path.exists():
        return VendorCheckReport(
            pinned_version="?",
            findings=(VendorFinding(MANIFEST_NAME, False, "manifest missing"),),
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return VendorCheckReport(
            pinned_version="?",
            findings=(VendorFinding(MANIFEST_NAME, False, f"invalid JSON: {exc}"),),
        )
    pinned = str(manifest.get("benchkit_version") or "?")
    hashes = manifest.get("hashes") or {}
    findings: list[VendorFinding] = []
    for entry in manifest.get("files", []):
        target = str(entry.get("target", ""))
        path = Path(consumer_root) / target
        if not path.exists():
            findings.append(VendorFinding(target, False, "file missing"))
            continue
        header, payload = _split_header(path.read_text(encoding="utf-8"))
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        problems: list[str] = []
        if header is None:
            problems.append("vendor header missing")
        else:
            header_version, header_hash16 = _parse_header(header)
            if header_hash16 != digest[:16]:
                problems.append("header hash != contents (hand-edit?)")
            if header_version != pinned:
                problems.append(
                    f"header pins benchkit@{header_version} but manifest pins {pinned}"
                )
        recorded = hashes.get(target)
        if recorded is None:
            problems.append("no hash recorded in manifest (never synced?)")
        elif recorded != digest:
            problems.append("manifest hash != contents")
        if problems:
            findings.append(VendorFinding(target, False, "; ".join(problems)))
        else:
            findings.append(VendorFinding(target, True, f"sha256:{digest[:16]}"))
    if not findings:
        findings.append(VendorFinding(MANIFEST_NAME, False, "manifest lists no files"))
    return VendorCheckReport(pinned_version=pinned, findings=tuple(findings))


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "root", nargs="?", default=".", help="consumer repo root (default: cwd)"
    )
    args = parser.parse_args()
    report = check_consumer(Path(args.root).resolve())
    for finding in report.findings:
        print(f"{'OK  ' if finding.ok else 'DRIFT'} {finding.target} — {finding.detail}")
    print(report.summary())
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
