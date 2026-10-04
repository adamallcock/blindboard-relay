# Vendored from benchkit@0.3.10 (sha256:a083b0de16685092). Do not hand-edit; run 'benchkit sync' to update.
"""Claim-blocker audit + evidence ledger (ported from
obviousbench.publication.paper_claims / paper_claim_ledger, benchmark
assumptions removed).

The discipline: a manuscript statement is either backed by a frozen
artifact or visibly marked with \\obtodo{...} / \\claimblocked{...}
(macros provided by benchkit.sty). This audit scans the TeX sources for
unresolved markers; it is a hard gate — the ledger is editorial guidance
that turns each marker into artifact-backed replacement work.

Port notes (no silent semantics changes):
- marker set, definition-line skipping, and brace-matching marker-text
  extraction are verbatim from obviousbench;
- the obviousbench ledger classified markers into categories wired to
  copybench-specific artifact paths; that table was benchmark-specific,
  so classification is now a pluggable callable (default: one generic
  category demanding direct artifact evidence). Pass your own classifier
  to reproduce per-benchmark guidance.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

MARKERS = ("claimblocked", "obtodo")


@dataclass(frozen=True)
class ClaimMarker:
    path: Path
    line_number: int
    marker: str
    line: str


@dataclass(frozen=True)
class ClaimAuditResult:
    output_path: Path | None
    markers: tuple[ClaimMarker, ...]

    @property
    def ok(self) -> bool:
        return not self.markers

    @property
    def claimblocked_count(self) -> int:
        return sum(marker.marker == "claimblocked" for marker in self.markers)

    @property
    def obtodo_count(self) -> int:
        return sum(marker.marker == "obtodo" for marker in self.markers)


def find_claim_markers(paper_dir: Path) -> tuple[ClaimMarker, ...]:
    """Find unresolved claim markers in every *.tex under paper_dir
    (definition lines and the vendored benchkit.sty are not markers)."""
    found: list[ClaimMarker] = []
    for path in sorted(Path(paper_dir).rglob("*.tex")):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if _is_marker_definition(line):
                continue
            for marker in MARKERS:
                if f"\\{marker}" in line:
                    found.append(
                        ClaimMarker(
                            path=path,
                            line_number=line_number,
                            marker=marker,
                            line=line.strip(),
                        )
                    )
    return tuple(found)


def audit_claims(
    paper_dir: Path,
    *,
    output_path: Path | None = None,
    title: str = "Paper Claim Blocker Audit",
) -> ClaimAuditResult:
    markers = find_claim_markers(paper_dir)
    result = ClaimAuditResult(output_path=output_path, markers=markers)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            _render_audit_markdown(result, Path(paper_dir), title), encoding="utf-8"
        )
    return result


def _is_marker_definition(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith(
        ("\\newcommand{\\claimblocked}", "\\newcommand{\\obtodo}")
    )


def _render_audit_markdown(result: ClaimAuditResult, paper_dir: Path, title: str) -> str:
    lines = [
        "---",
        f"title: {title}",
        "type: review",
        "status: current",
        "---",
        "",
        f"# {title}",
        "",
        f"Overall status: {'PASS' if result.ok else 'FAIL'}",
        "",
        f"Unresolved markers: {len(result.markers)}",
        "",
        f"- `claimblocked`: {result.claimblocked_count}",
        f"- `obtodo`: {result.obtodo_count}",
        "",
    ]
    if result.markers:
        lines.extend(["## Markers", ""])
        for marker in result.markers:
            relative = marker.path.relative_to(paper_dir)
            lines.append(
                f"- `{relative}:{marker.line_number}` `{marker.marker}`: "
                f"{_truncate(marker.line)}"
            )
        lines.append("")
    return "\n".join(lines)


def _truncate(text: str, limit: int = 160) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


# --- Evidence ledger -------------------------------------------------------

#: classifier(relative_path, marker_text) ->
#:   (category, required_evidence, source_artifacts, acceptance)
Classifier = Callable[[Path, str], tuple[str, str, tuple[str, ...], str]]


def generic_classifier(
    relative_path: Path, marker_text: str
) -> tuple[str, str, tuple[str, ...], str]:
    return (
        "general claim evidence",
        "Direct artifact evidence for the marked statement.",
        (),
        "Marker is removed only after the source artifact supports replacement text.",
    )


@dataclass(frozen=True)
class ClaimLedgerEntry:
    path: Path
    line_number: int
    marker: str
    category: str
    marker_text: str
    required_evidence: str
    source_artifacts: tuple[str, ...]
    acceptance: str


@dataclass(frozen=True)
class ClaimLedgerResult:
    output_path: Path | None
    entries: tuple[ClaimLedgerEntry, ...]

    @property
    def ok(self) -> bool:
        return not self.entries

    @property
    def blocked_count(self) -> int:
        return len(self.entries)


def build_claim_ledger(
    paper_dir: Path,
    *,
    output_path: Path | None = None,
    title: str = "Paper Claim Evidence Ledger",
    classifier: Classifier = generic_classifier,
) -> ClaimLedgerResult:
    """Render a replacement plan for every unresolved paper marker."""
    paper_dir = Path(paper_dir)
    entries = []
    for marker in find_claim_markers(paper_dir):
        relative = marker.path.relative_to(paper_dir)
        marker_text = _extract_marker_text(marker)
        category, evidence, artifacts, acceptance = classifier(relative, marker_text)
        entries.append(
            ClaimLedgerEntry(
                path=relative,
                line_number=marker.line_number,
                marker=marker.marker,
                category=category,
                marker_text=marker_text,
                required_evidence=evidence,
                source_artifacts=tuple(artifacts),
                acceptance=acceptance,
            )
        )
    result = ClaimLedgerResult(output_path=output_path, entries=tuple(entries))
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(_render_ledger_markdown(result, title), encoding="utf-8")
    return result


def _extract_marker_text(marker: ClaimMarker) -> str:
    """Brace-matched body of the marker command (may span lines)."""
    lines = marker.path.read_text(encoding="utf-8").splitlines()
    source = "\n".join(lines[marker.line_number - 1 :])
    command = f"\\{marker.marker}"
    start = source.find(command)
    if start == -1:
        return _clean(marker.line)
    opening = source.find("{", start + len(command))
    if opening == -1:
        return _clean(marker.line)
    depth = 1
    body_chars: list[str] = []
    for char in source[opening + 1 :]:
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return _clean("".join(body_chars))
        body_chars.append(char)
    return _clean(source[start:])


def _clean(line: str) -> str:
    return " ".join(line.strip().split())


def _render_ledger_markdown(result: ClaimLedgerResult, title: str) -> str:
    lines = [
        "---",
        f"title: {title}",
        "type: review",
        f"status: {'ready' if result.ok else 'blocked'}",
        "---",
        "",
        f"# {title}",
        "",
        "This ledger turns unresolved manuscript markers into artifact-backed",
        "replacement work. It is editorial guidance; the claim-blocker audit",
        "remains the hard gate.",
        "",
        f"Overall status: {'PASS' if result.ok else 'BLOCKED'}",
        "",
        f"Blocked entries: {result.blocked_count}",
        "",
    ]
    if not result.entries:
        lines.append("No unresolved claim markers were found.")
        lines.append("")
        return "\n".join(lines)
    lines.extend(
        [
            "| Location | Marker | Category | Required evidence | Source artifacts | Acceptance |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for entry in result.entries:
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(f"{entry.path}:{entry.line_number}"),
                    _cell(entry.marker),
                    _cell(entry.category),
                    _cell(entry.required_evidence),
                    _cell(", ".join(entry.source_artifacts)),
                    _cell(entry.acceptance),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Marker Text", ""])
    for entry in result.entries:
        lines.append(
            f"- `{entry.path}:{entry.line_number}` `{entry.marker}`: "
            f"{_cell(entry.marker_text)}"
        )
    lines.append("")
    return "\n".join(lines)


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()
