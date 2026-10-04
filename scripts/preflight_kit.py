# Vendored from benchkit@0.3.10 (sha256:f72cfafb94f23bba). Do not hand-edit; run 'benchkit sync' to update.
"""arXiv submission preflight checklist (ported from
obviousbench.publication.arxiv_preflight; generic core).

Aggregates the cheap local checks into one human-readable checklist that
must be all-PASS before upload:

- the consumer's own readiness gates (declared via the gates framework —
  this is where the obviousbench dataset/item-card/scorer-gold/human-
  baseline gates now live, as per-benchmark GateSpecs);
- the claim-blocker audit;
- the source-bundle audit;
- required frozen-evidence files (consumer-declared name -> path);
- the LaTeX toolchain and the built PDF;
- the human-confirmed submission-metadata note.

Port notes: obviousbench's readiness gates imported its dataset schemas
(pydantic), item cards, and scorer-gold fixtures — benchmark-specific by
construction; they are not ported. Consumers declare equivalent gates and
pass the evaluated results in. Everything else keeps obviousbench
semantics (required-file checks, toolchain probe, metadata confirmation).
"""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from arxiv_bundle_kit import (
    ArxivBundleAuditInputs,
    audit_arxiv_bundle,
)
from arxiv_metadata_kit import audit_submission_metadata
from claims_kit import audit_claims
from gates_kit import GateResult

PreflightStatus = Literal["pass", "fail"]
DEFAULT_LATEX_TOOLCHAIN_COMMANDS = ("latexmk", "pdflatex", "tectonic")


@dataclass(frozen=True)
class PreflightInputs:
    paper_dir: Path
    bundle_path: Path
    output_path: Path
    pdf_path: Path
    gate_results: Sequence[GateResult] = ()
    required_files: dict[str, Path] = field(default_factory=dict)
    metadata_confirmation_path: Path | None = None
    claim_audit_output_path: Path | None = None
    bundle_audit_output_path: Path | None = None
    bundle_required_members: Sequence[str] = ("main.tex", "references.bib")
    bundle_required_prefixes: Sequence[str] = ()
    latex_toolchain_commands: Sequence[str] = DEFAULT_LATEX_TOOLCHAIN_COMMANDS
    available_latex_tools: Sequence[str] | None = None
    title: str = "arXiv Submission Checklist"


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    status: PreflightStatus
    evidence: str
    next_action: str


@dataclass(frozen=True)
class PreflightResult:
    output_path: Path
    checks: tuple[PreflightCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.status == "pass" for check in self.checks)

    @property
    def passed_count(self) -> int:
        return sum(check.status == "pass" for check in self.checks)

    @property
    def failed_count(self) -> int:
        return sum(check.status == "fail" for check in self.checks)

    def check_by_name(self, name: str) -> PreflightCheck:
        for check in self.checks:
            if check.name == name:
                return check
        raise KeyError(name)


def build_preflight(inputs: PreflightInputs) -> PreflightResult:
    """Run cheap local checks and write a human-readable submission checklist."""
    checks: list[PreflightCheck] = []

    for gate in inputs.gate_results:
        checks.append(
            PreflightCheck(
                name=f"gate: {gate.name}",
                status="pass" if not gate.blocking else "fail",
                evidence=f"{gate.status}: {gate.summary}",
                next_action="None." if not gate.blocking else "Resolve the failing gate.",
            )
        )

    claim_result = audit_claims(
        inputs.paper_dir, output_path=inputs.claim_audit_output_path
    )
    checks.append(
        PreflightCheck(
            name="paper claim blockers",
            status="pass" if claim_result.ok else "fail",
            evidence=(
                f"{len(claim_result.markers)} unresolved marker(s): "
                f"{claim_result.claimblocked_count} claimblocked, "
                f"{claim_result.obtodo_count} obtodo."
                + (f" Audit: {claim_result.output_path}" if claim_result.output_path else "")
            ),
            next_action=(
                "None."
                if claim_result.ok
                else "Replace each marker only after supporting evidence exists."
            ),
        )
    )

    bundle_result = audit_arxiv_bundle(
        ArxivBundleAuditInputs(
            bundle_path=inputs.bundle_path,
            output_path=inputs.bundle_audit_output_path,
            required_members=inputs.bundle_required_members,
            required_prefixes=inputs.bundle_required_prefixes,
        )
    )
    checks.append(
        PreflightCheck(
            name="source bundle audit",
            status="pass" if bundle_result.ok else "fail",
            evidence=_bundle_evidence(bundle_result.members, bundle_result.issues)
            + (f" Audit: {bundle_result.output_path}" if bundle_result.output_path else ""),
            next_action=(
                "None."
                if bundle_result.ok
                else "Regenerate the bundle and remove forbidden or missing files."
            ),
        )
    )

    for name, path in inputs.required_files.items():
        checks.append(
            _required_file_check(
                name,
                path,
                pass_message=f"Required {name} file exists.",
                fail_action=f"Create or confirm the {name} file.",
            )
        )

    checks.append(
        _required_file_check(
            "PDF build artifact",
            inputs.pdf_path,
            pass_message="Local paper PDF exists.",
            fail_action="Build the PDF in a LaTeX-enabled environment.",
        )
    )
    checks.append(_latex_toolchain_check(inputs))
    checks.append(_submission_metadata_check(inputs.metadata_confirmation_path))

    result = PreflightResult(output_path=inputs.output_path, checks=tuple(checks))
    inputs.output_path.parent.mkdir(parents=True, exist_ok=True)
    inputs.output_path.write_text(
        _render_markdown(result, inputs.title), encoding="utf-8"
    )
    return result


def _bundle_evidence(members: Sequence[str], issues: Sequence[str]) -> str:
    if not issues:
        return f"{len(members)} bundle member(s), 0 issue(s)."
    shown = "; ".join(issues[:3])
    if len(issues) > 3:
        shown += f"; {len(issues) - 3} additional issue(s) omitted."
    return f"{len(members)} bundle member(s), {len(issues)} issue(s): {shown}."


def _required_file_check(
    name: str,
    path: Path | None,
    *,
    pass_message: str,
    fail_action: str,
) -> PreflightCheck:
    if path is None:
        return PreflightCheck(
            name=name, status="fail", evidence="No path configured.", next_action=fail_action
        )
    if not path.exists():
        return PreflightCheck(
            name=name, status="fail", evidence=f"Missing file: {path}", next_action=fail_action
        )
    if path.stat().st_size == 0:
        return PreflightCheck(
            name=name, status="fail", evidence=f"Empty file: {path}", next_action=fail_action
        )
    return PreflightCheck(
        name=name, status="pass", evidence=f"{pass_message} Path: {path}", next_action="None."
    )


def _latex_toolchain_check(inputs: PreflightInputs) -> PreflightCheck:
    available = (
        tuple(inputs.available_latex_tools)
        if inputs.available_latex_tools is not None
        else tuple(
            command
            for command in inputs.latex_toolchain_commands
            if shutil.which(command)
        )
    )
    if available:
        return PreflightCheck(
            name="LaTeX build toolchain",
            status="pass",
            evidence="Available command(s): " + ", ".join(available),
            next_action="None.",
        )
    return PreflightCheck(
        name="LaTeX build toolchain",
        status="fail",
        evidence="No command found among: " + ", ".join(inputs.latex_toolchain_commands),
        next_action="Install latexmk/pdflatex or tectonic before PDF inspection.",
    )


def _submission_metadata_check(path: Path | None) -> PreflightCheck:
    result = audit_submission_metadata(path)
    if not result.ok:
        evidence = "; ".join(result.issues[:4])
        if len(result.issues) > 4:
            evidence += f"; {len(result.issues) - 4} additional issue(s) omitted"
        return PreflightCheck(
            name="submission metadata confirmation",
            status="fail",
            evidence=evidence,
            next_action=(
                "Confirm final abstract, authors, arXiv category, license, "
                "release links, submitter status, and AI-tool disclosure."
            ),
        )
    return PreflightCheck(
        name="submission metadata confirmation",
        status="pass",
        evidence=f"Required metadata is confirmed. Path: {result.path}",
        next_action="None.",
    )


def _render_markdown(result: PreflightResult, title: str) -> str:
    status = "ready" if result.ok else "blocked"
    lines = [
        "---",
        f"title: {title}",
        "type: review",
        f"status: {status}",
        "---",
        "",
        f"# {title}",
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
    lines.append("")
    return "\n".join(lines)


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()
