# Vendored from benchkit@0.3.10 (sha256:f7fa75ce235852e2). Do not hand-edit; run 'benchkit sync' to update.
"""PDF build-state audit (ported from
obviousbench.publication.paper_pdf_audit; generic core, parameterized).

Records the current PDF build and inspection state WITHOUT invoking LaTeX:
toolchain availability, the static source audit, the PDF artifact, required
standalone figures (present, non-placeholder-sized, no placeholder text),
and the LaTeX log. Should pass before a source bundle is treated as
upload-ready.

Port notes:
- obviousbench hardcoded main.pdf/main.log and its four paper figures;
  both are now parameters (required_figures defaults to empty: consumers
  list the figure files their paper cannot ship without).
- an empty required_figures no longer reports a clean PASS (which read as
  "figures checked" when nothing was checked). It PASSes with an explicit
  "NOT checked" notice; set require_figures=True to make an empty list a
  hard FAIL for submission-stage consumers that must declare their figures.
- log/figure heuristics (error patterns, 5 kB placeholder threshold,
  marker strings) are unchanged obviousbench defaults, overridable.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from source_audit_kit import SourceAuditInputs, audit_paper_source

PdfAuditStatus = Literal["pass", "fail"]
DEFAULT_LATEX_TOOLS = ("latexmk", "pdflatex", "tectonic")
LOG_ERROR_PATTERNS = (
    r"^!",
    r"LaTeX Error",
    r"Undefined control sequence",
    r"Emergency stop",
    r"Fatal error",
    r"Citation .* undefined",
    r"Reference .* undefined",
    r"Overfull \\hbox",
    r"Overfull \\vbox",
)
DEFAULT_FIGURE_PLACEHOLDER_MARKERS = (
    "No result rows available yet",
    "No rows available.",
    "No plottable rows available.",
)
MIN_FIGURE_BYTES = 5_000


@dataclass(frozen=True)
class PdfAuditInputs:
    paper_dir: Path
    output_path: Path | None = None
    main_tex: str = "main.tex"
    pdf_path: Path | None = None  # default: paper_dir / (main_tex stem + '.pdf')
    log_path: Path | None = None  # default: paper_dir / (main_tex stem + '.log')
    figures_dir: Path | None = None  # default: paper_dir / 'figures'
    required_figures: Sequence[str] = ()
    require_figures: bool = False  # empty required_figures -> hard FAIL, not a notice
    figure_placeholder_markers: Sequence[str] = DEFAULT_FIGURE_PLACEHOLDER_MARKERS
    latex_tools: Sequence[str] = DEFAULT_LATEX_TOOLS
    available_latex_tools: Sequence[str] | None = None
    source_audit_output_path: Path | None = None
    title: str = "Paper PDF Build Audit"


@dataclass(frozen=True)
class PdfCheck:
    name: str
    status: PdfAuditStatus
    evidence: str
    next_action: str


@dataclass(frozen=True)
class PdfAuditResult:
    output_path: Path | None
    checks: tuple[PdfCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.status == "pass" for check in self.checks)

    @property
    def passed_count(self) -> int:
        return sum(check.status == "pass" for check in self.checks)

    @property
    def failed_count(self) -> int:
        return sum(check.status == "fail" for check in self.checks)

    def check_by_name(self, name: str) -> PdfCheck:
        for check in self.checks:
            if check.name == name:
                return check
        raise KeyError(name)


def audit_paper_pdf(inputs: PdfAuditInputs) -> PdfAuditResult:
    """Write a PDF-build audit without invoking LaTeX."""
    paper_dir = Path(inputs.paper_dir)
    stem = Path(inputs.main_tex).stem
    pdf_path = inputs.pdf_path or paper_dir / f"{stem}.pdf"
    log_path = inputs.log_path or paper_dir / f"{stem}.log"
    source_result = audit_paper_source(
        SourceAuditInputs(
            paper_dir=paper_dir,
            output_path=inputs.source_audit_output_path,
            main_tex=inputs.main_tex,
        )
    )
    checks = (
        _toolchain_check(inputs),
        _source_audit_check(source_result),
        _pdf_artifact_check(pdf_path),
        _figure_artifacts_check(
            inputs.figures_dir or paper_dir / "figures",
            inputs.required_figures,
            inputs.figure_placeholder_markers,
            inputs.require_figures,
        ),
        _log_check(log_path),
    )
    result = PdfAuditResult(output_path=inputs.output_path, checks=checks)
    if inputs.output_path is not None:
        inputs.output_path.parent.mkdir(parents=True, exist_ok=True)
        inputs.output_path.write_text(
            _render_markdown(result, inputs.title), encoding="utf-8"
        )
    return result


def _toolchain_check(inputs: PdfAuditInputs) -> PdfCheck:
    available = (
        tuple(inputs.available_latex_tools)
        if inputs.available_latex_tools is not None
        else tuple(tool for tool in inputs.latex_tools if shutil.which(tool))
    )
    if available:
        return PdfCheck(
            name="LaTeX toolchain",
            status="pass",
            evidence="Available command(s): " + ", ".join(available),
            next_action="None.",
        )
    return PdfCheck(
        name="LaTeX toolchain",
        status="fail",
        evidence="No command found among: " + ", ".join(inputs.latex_tools),
        next_action="Install latexmk/pdflatex or tectonic before final PDF build.",
    )


def _source_audit_check(source_result) -> PdfCheck:
    where = f" Audit: {source_result.output_path}" if source_result.output_path else ""
    if source_result.ok:
        return PdfCheck(
            name="static source audit",
            status="pass",
            evidence=f"{source_result.passed_count} passed, 0 failed.{where}",
            next_action="None.",
        )
    return PdfCheck(
        name="static source audit",
        status="fail",
        evidence=(
            f"{source_result.passed_count} passed, "
            f"{source_result.failed_count} failed.{where}"
        ),
        next_action="Resolve static source-audit failures before final PDF inspection.",
    )


def _pdf_artifact_check(path: Path) -> PdfCheck:
    if not path.exists():
        return PdfCheck(
            name="PDF artifact",
            status="fail",
            evidence=f"Missing file: {path}",
            next_action="Build the PDF in a LaTeX-enabled environment.",
        )
    if path.stat().st_size == 0:
        return PdfCheck(
            name="PDF artifact",
            status="fail",
            evidence=f"Empty file: {path}",
            next_action="Rebuild the PDF and inspect the LaTeX output.",
        )
    return PdfCheck(
        name="PDF artifact",
        status="pass",
        evidence=f"PDF exists and is non-empty: {path}",
        next_action="None.",
    )


def _figure_artifacts_check(
    figures_dir: Path,
    required_figures: Sequence[str],
    placeholder_markers: Sequence[str],
    require_figures: bool = False,
) -> PdfCheck:
    if not required_figures:
        if require_figures:
            return PdfCheck(
                name="standalone figure artifacts",
                status="fail",
                evidence="No required standalone figures declared, but require_figures=True.",
                next_action="List the paper's required figure files in required_figures.",
            )
        return PdfCheck(
            name="standalone figure artifacts",
            status="pass",
            evidence="No required figures declared -- figure coverage NOT checked "
            "(set require_figures=True to enforce).",
            next_action="If this paper ships standalone figures, list them in required_figures.",
        )
    paths = [figures_dir / name for name in required_figures]
    missing = [path for path in paths if not path.exists()]
    if missing:
        return PdfCheck(
            name="standalone figure artifacts",
            status="fail",
            evidence="missing: " + ", ".join(str(path) for path in missing),
            next_action="Run paper asset generation against the frozen final results.",
        )
    tiny = [path for path in paths if path.stat().st_size < MIN_FIGURE_BYTES]
    if tiny:
        return PdfCheck(
            name="standalone figure artifacts",
            status="fail",
            evidence=(
                "placeholder-sized figure(s): "
                + ", ".join(f"{path} ({path.stat().st_size} bytes)" for path in tiny)
            ),
            next_action="Regenerate non-placeholder figure files from final results.",
        )
    marker_hits: list[str] = []
    for path in paths:
        text = path.read_bytes().decode("latin1", errors="ignore")
        for marker in placeholder_markers:
            if marker in text:
                marker_hits.append(f"{path}: {marker}")
    if marker_hits:
        return PdfCheck(
            name="standalone figure artifacts",
            status="fail",
            evidence="; ".join(marker_hits),
            next_action="Regenerate figures from final result artifacts.",
        )
    return PdfCheck(
        name="standalone figure artifacts",
        status="pass",
        evidence=f"{len(paths)}/{len(paths)} figure file(s) present and non-placeholder.",
        next_action="None.",
    )


def _log_check(path: Path) -> PdfCheck:
    if not path.exists():
        return PdfCheck(
            name="LaTeX build log",
            status="fail",
            evidence=f"Missing file: {path}",
            next_action="Run a real PDF build and inspect the resulting log "
            "(tectonic: pass --keep-logs).",
        )
    text = path.read_text(encoding="utf-8", errors="replace")
    issues = _log_issues(text)
    if issues:
        return PdfCheck(
            name="LaTeX build log",
            status="fail",
            evidence=_summarize(issues),
            next_action="Fix fatal, undefined-reference, and overfull-box log issues.",
        )
    return PdfCheck(
        name="LaTeX build log",
        status="pass",
        evidence=f"No fatal, undefined-reference, or overfull-box markers in {path}.",
        next_action="None.",
    )


def _log_issues(text: str) -> list[str]:
    issues: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for pattern in LOG_ERROR_PATTERNS:
            if re.search(pattern, line):
                issues.append(f"line {line_number}: {line.strip()}")
                break
    return issues


def _render_markdown(result: PdfAuditResult, title: str) -> str:
    lines = [
        "---",
        f"title: {title}",
        "type: review",
        f"status: {'ready' if result.ok else 'blocked'}",
        "---",
        "",
        f"# {title}",
        "",
        "This audit records the current PDF build and inspection state without",
        "invoking LaTeX. It should pass before the arXiv source bundle is treated",
        "as upload-ready.",
        "",
        f"Overall status: {'PASS' if result.ok else 'BLOCKED'}",
        "",
        f"Summary: {result.passed_count} passed, {result.failed_count} failed.",
        "",
        "| Check | Status | Evidence | Next action |",
        "| --- | --- | --- | --- |",
    ]
    for check in result.checks:
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(check.name),
                    check.status.upper(),
                    _cell(check.evidence),
                    _cell(check.next_action),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Final PDF Rule",
            "",
            "Do not mark the source bundle as arXiv-ready until this audit passes",
            "after a real PDF build, and the generated PDF has been visually",
            "inspected for table fit, figure rendering, citation resolution, and",
            "title/abstract consistency.",
            "",
        ]
    )
    return "\n".join(lines)


def _summarize(values: Sequence[str], *, limit: int = 6) -> str:
    shown = "; ".join(values[:limit])
    if len(values) > limit:
        shown += f"; {len(values) - limit} additional issue(s) omitted"
    return shown


def _cell(value: str) -> str:
    return " ".join(value.split()).replace("|", "\\|")
