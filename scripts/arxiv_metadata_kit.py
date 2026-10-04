# Vendored from benchkit@0.3.10 (sha256:4d2828666c69b37d). Do not hand-edit; run 'benchkit sync' to update.
"""arXiv submission-metadata template + audit (ported from
obviousbench.publication.arxiv_metadata; generic core).

The template is a human-confirmed handoff note for the arXiv upload form.
It starts as `draft`; the preflight must not pass until status and
metadata_status are `confirmed`, placeholders are gone, and every boolean
confirmation is true.

Port notes (no silent semantics changes):
- required text/boolean fields and placeholder markers are verbatim from
  obviousbench;
- obviousbench parsed the frontmatter with PyYAML; benchkit is
  stdlib-first, so this port parses the strict flat subset the template
  actually uses (scalars, quoted strings, booleans, one-level `- item`
  lists). Exotic YAML in a hand-edited note fails the audit loudly
  instead of parsing differently.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REQUIRED_TEXT_FIELDS = (
    "article_title",
    "abstract",
    "primary_category",
    "license",
    "comments",
    "repository_url",
    "dataset_url",
    "ai_tool_disclosure",
)
REQUIRED_BOOLEAN_FIELDS = (
    "submitter_registered_author",
    "endorsement_checked",
    "submitter_is_author_or_authorized_proxy",
    "title_and_abstract_checked",
)
PLACEHOLDER_MARKERS = (
    "TODO",
    "TBD",
    "claimblocked",
    "obtodo",
    "<",
    ">",
)


@dataclass(frozen=True)
class ArxivMetadataInputs:
    output_path: Path
    article_title: str = "TODO(final article title)"
    primary_category: str = "cs.CL"
    secondary_categories: tuple[str, ...] = ("cs.AI",)
    title: str = "arXiv Submission Metadata"


@dataclass(frozen=True)
class ArxivMetadataAuditResult:
    path: Path
    issues: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.issues


def build_submission_metadata_template(inputs: ArxivMetadataInputs) -> Path:
    """Write a draft arXiv metadata note that must be confirmed before upload."""
    inputs.output_path.parent.mkdir(parents=True, exist_ok=True)
    inputs.output_path.write_text(_render_template(inputs), encoding="utf-8")
    return inputs.output_path


def audit_submission_metadata(path: Path | None) -> ArxivMetadataAuditResult:
    if path is None:
        return ArxivMetadataAuditResult(
            path=Path(""),
            issues=("metadata confirmation path is not configured",),
        )
    if not path.exists():
        return ArxivMetadataAuditResult(
            path=path, issues=(f"metadata file is missing: {path}",)
        )
    if path.stat().st_size == 0:
        return ArxivMetadataAuditResult(
            path=path, issues=(f"metadata file is empty: {path}",)
        )

    frontmatter, parse_issue = _load_frontmatter(path)
    issues: list[str] = []
    if parse_issue is not None:
        return ArxivMetadataAuditResult(path=path, issues=(parse_issue,))

    if frontmatter.get("metadata_status") != "confirmed":
        issues.append("metadata_status must be confirmed")
    if frontmatter.get("status") != "confirmed":
        issues.append("status must be confirmed")

    authors = frontmatter.get("authors")
    if not isinstance(authors, list) or not authors:
        issues.append("authors must be a non-empty list")
    else:
        for index, author in enumerate(authors, start=1):
            if not _is_non_placeholder_text(author):
                issues.append(f"authors[{index}] is empty or placeholder text")

    secondary_categories = frontmatter.get("secondary_categories")
    if secondary_categories is not None and not isinstance(secondary_categories, list):
        issues.append("secondary_categories must be a list when present")

    for field in REQUIRED_TEXT_FIELDS:
        value = frontmatter.get(field)
        if not _is_non_placeholder_text(value):
            issues.append(f"{field} is missing, empty, or TODO placeholder text")

    for field in REQUIRED_BOOLEAN_FIELDS:
        if frontmatter.get(field) is not True:
            issues.append(f"{field} must be true")

    return ArxivMetadataAuditResult(path=path, issues=tuple(issues))


def _render_template(inputs: ArxivMetadataInputs) -> str:
    secondary_lines = "\n".join(
        f'  - "{category}"' for category in inputs.secondary_categories
    )
    return f"""---
title: {inputs.title}
type: review
status: draft
metadata_status: draft
article_title: "{inputs.article_title}"
authors:
  - "TODO(confirm author list, order, affiliations, and contact email)"
abstract: "TODO(replace after readiness gates pass and final results are frozen)"
primary_category: "{inputs.primary_category}"
secondary_categories:
{secondary_lines}
license: "TODO(confirm arXiv license selection)"
comments: "TODO(confirm final page count, figures, tables, and release links)"
repository_url: "TODO(confirm public repository URL)"
dataset_url: "TODO(confirm public data or artifact URL)"
ai_tool_disclosure: "TODO(confirm disclosure text for author workflow)"
submitter_registered_author: false
endorsement_checked: false
submitter_is_author_or_authorized_proxy: false
title_and_abstract_checked: false
---

# {inputs.title}

This note is the human-confirmed metadata handoff for the arXiv upload form.
It intentionally starts as `draft`; the submission preflight should not pass
until `status` and `metadata_status` are changed to `confirmed`, placeholders
are removed, and all boolean confirmation fields are true.

Official arXiv references checked for this template:

- https://info.arxiv.org/help/submit/index.html
- https://info.arxiv.org/help/prep.html
- https://info.arxiv.org/help/license/index.html
- https://arxiv.org/category_taxonomy

Submission-specific decisions still required:

- Confirm the primary and any secondary categories.
- Confirm the author list, author order, affiliations, and submitter account.
- Confirm whether an endorsement is needed for the selected category.
- Confirm the license selection.
- Confirm public repository and data release links.
- Confirm final title and abstract exactly match the reviewed manuscript.
- Record the pinned benchkit version in the reproducibility statement.
"""


def _load_frontmatter(path: Path) -> tuple[dict, str | None]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, "metadata file is missing YAML frontmatter"
    try:
        _, raw_frontmatter, _ = text.split("---", 2)
    except ValueError:
        return {}, "metadata file has malformed YAML frontmatter"
    return _parse_flat_yaml(raw_frontmatter)


def _parse_flat_yaml(raw: str) -> tuple[dict, str | None]:
    """Parse the strict flat frontmatter subset the template uses:
    `key: value` scalars (quoted or bare, true/false booleans) and
    one-level `key:` + `  - item` lists. Anything else is a parse issue."""
    data: dict[str, object] = {}
    current_list: list[str] | None = None
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue
        stripped = line.strip()
        if stripped.startswith("- "):
            if current_list is None:
                return {}, f"frontmatter line {line_number}: list item without a key"
            current_list.append(_scalar(stripped[2:]))
            continue
        if ":" not in stripped:
            return {}, f"frontmatter line {line_number}: expected 'key: value'"
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()
        if not key:
            return {}, f"frontmatter line {line_number}: empty key"
        if value == "":
            new_list: list[str] = []
            data[key] = new_list
            current_list = new_list
        else:
            data[key] = _typed_scalar(value)
            current_list = None
    return data, None


def _scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _typed_scalar(value: str):
    text = _scalar(value)
    if value.strip() in {"true", "True"}:
        return True
    if value.strip() in {"false", "False"}:
        return False
    return text


def _is_non_placeholder_text(value: object) -> bool:
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    return not any(marker.lower() in lowered for marker in PLACEHOLDER_MARKERS)
