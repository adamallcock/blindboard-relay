# Vendored from benchkit@0.3.10 (sha256:6ce876d2e6b12461). Do not hand-edit; run 'benchkit sync' to update.
"""arXiv source-bundle packaging + audit (ported from
obviousbench.publication.arxiv_source_bundle plus the paper/Makefile
`arxiv-package` tar recipe; generic core, parameterized).

- ``build_arxiv_bundle``: deterministic-ish tar.gz of the paper source
  (tex, bib, tables/figures dirs), excluding built PDFs and aux files —
  the Makefile pattern, as a function.
- ``audit_arxiv_bundle``: inspect the bundle BEFORE upload — required
  members present, no forbidden paths (results, caches, venvs), no
  sensitive-looking filenames.

Port notes: obviousbench required main.tex + references.bib + a sections/
prefix; those are now parameters (default keeps main.tex+references.bib,
requires no prefix). Forbidden path/name lists are the obviousbench
defaults, overridable.
"""

from __future__ import annotations

import tarfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_FORBIDDEN_PATH_PARTS = (
    "results/raw",
    "results/summaries",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".DS_Store",
)
DEFAULT_FORBIDDEN_NAME_PARTS = (
    "api_key",
    "apikey",
    "password",
    "secret",
    "credential",
)
DEFAULT_REQUIRED_MEMBERS = ("main.tex", "references.bib")
DEFAULT_EXCLUDE_SUFFIXES = (".pdf", ".aux", ".log", ".out", ".bbl", ".blg", ".fls", ".toc")


def build_arxiv_bundle(
    paper_dir: Path,
    bundle_path: Path,
    *,
    members: Sequence[str],
    exclude_suffixes: Sequence[str] = DEFAULT_EXCLUDE_SUFFIXES,
    keep_pdf_figures: bool = True,
) -> list[str]:
    """Create bundle_path (tar.gz) from the listed members (files or
    directories, relative to paper_dir). Build products are excluded by
    suffix — except figure PDFs, which arXiv needs (anything under a
    directory named 'figures' is kept when keep_pdf_figures).
    Returns the archived member names."""
    paper_dir = Path(paper_dir)
    bundle_path = Path(bundle_path)
    bundle_path.parent.mkdir(parents=True, exist_ok=True)

    def include(path: Path) -> bool:
        relative = path.relative_to(paper_dir)
        if path.suffix.lower() in {s.lower() for s in exclude_suffixes}:
            return (
                keep_pdf_figures
                and path.suffix.lower() == ".pdf"
                and "figures" in relative.parts[:-1]
            )
        return True

    archived: list[str] = []
    with tarfile.open(bundle_path, "w:gz") as archive:
        for member in members:
            member_path = paper_dir / member
            if not member_path.exists():
                raise FileNotFoundError(f"bundle member missing: {member_path}")
            paths = (
                sorted(p for p in member_path.rglob("*") if p.is_file())
                if member_path.is_dir()
                else [member_path]
            )
            for path in paths:
                if not include(path):
                    continue
                name = str(path.relative_to(paper_dir))
                archive.add(path, arcname=name)
                archived.append(name)
    return archived


@dataclass(frozen=True)
class ArxivBundleAuditInputs:
    bundle_path: Path
    output_path: Path | None = None
    required_members: Sequence[str] = DEFAULT_REQUIRED_MEMBERS
    required_prefixes: Sequence[str] = ()
    forbidden_path_parts: Sequence[str] = DEFAULT_FORBIDDEN_PATH_PARTS
    forbidden_name_parts: Sequence[str] = DEFAULT_FORBIDDEN_NAME_PARTS
    title: str = "arXiv Source Bundle Audit"


@dataclass(frozen=True)
class ArxivBundleAuditResult:
    output_path: Path | None
    members: tuple[str, ...]
    issues: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def issue_count(self) -> int:
        return len(self.issues)


def audit_arxiv_bundle(inputs: ArxivBundleAuditInputs) -> ArxivBundleAuditResult:
    members, issues = _inspect_bundle(inputs)
    result = ArxivBundleAuditResult(
        output_path=inputs.output_path,
        members=members,
        issues=tuple(issues),
    )
    if inputs.output_path is not None:
        inputs.output_path.parent.mkdir(parents=True, exist_ok=True)
        inputs.output_path.write_text(
            _render_markdown(result, inputs.title), encoding="utf-8"
        )
    return result


def _inspect_bundle(inputs: ArxivBundleAuditInputs) -> tuple[tuple[str, ...], list[str]]:
    bundle_path = Path(inputs.bundle_path)
    if not bundle_path.exists():
        return (), [f"missing bundle: {bundle_path}"]
    issues: list[str] = []
    try:
        with tarfile.open(bundle_path, "r:gz") as archive:
            members = tuple(sorted(member.name for member in archive.getmembers()))
    except tarfile.TarError as exc:
        return (), [f"invalid tar.gz bundle: {exc}"]

    member_set = set(members)
    for required in inputs.required_members:
        if required not in member_set:
            issues.append(f"missing required member: {required}")
    for prefix in inputs.required_prefixes:
        if not any(member.startswith(prefix) for member in members):
            issues.append(f"missing required prefix: {prefix}")
    for member in members:
        lowered = member.lower()
        if any(part in lowered for part in inputs.forbidden_path_parts):
            issues.append(f"forbidden path in bundle: {member}")
        if any(part in lowered for part in inputs.forbidden_name_parts):
            issues.append(f"sensitive-looking filename in bundle: {member}")
    return members, issues


def _render_markdown(result: ArxivBundleAuditResult, title: str) -> str:
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
        f"Members: {len(result.members)}",
        "",
        f"Issues: {result.issue_count}",
        "",
    ]
    if result.issues:
        lines.extend(["## Issues", ""])
        lines.extend(f"- {issue}" for issue in result.issues)
        lines.append("")
    return "\n".join(lines)
