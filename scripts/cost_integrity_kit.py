# Vendored from benchkit@0.3.10 (sha256:c13ce66f15f91638). Do not hand-edit; run 'benchkit sync' to update.
"""Cost-integrity audit (ported from
obviousbench.publication.cost_integrity; generic core, plus a run-summary
world variant).

Guards against silently missing or partial cost accounting behind a
published cost claim. Two entry points for the two runner worlds:

- ``audit_comparison_costs``: the obviousbench comparison.csv world
  (columns: label/model, scored_samples, provider_errors, timeouts,
  total_tokens, estimated_cost_usd, cost_warnings, ...). Checks are the
  obviousbench originals: recorded cost warnings, successful samples with
  zero usage telemetry, nonzero tokens with zero cost, and an
  effective-price floor.
- ``audit_summary_costs``: the interactive-runner world (blindboard/relay
  summary.json: episodes, usage.{input,output}_tokens,
  cost_usd_list_price). Same spirit: episodes ran but no tokens; tokens
  but no/None cost; and, when the pricing registry knows the model, the
  recorded cost must match the list-price recomputation within tolerance
  (published costs are UNDISCOUNTED LIST — a discounted number here is a
  reporting bug, not a saving).

Port notes: the obviousbench repair-source/selection-audit check
(cumulative-cost-runs discipline) was tied to its cache/repair workflow;
it is kept, parameterized, and off unless a selection audit is supplied.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_LOW_USD_PER_MTOK = 0.01
DEFAULT_FULL_RERUN_SOURCES = frozenset({"repair3_xai_grok", "telemetry_rerun"})
DEFAULT_COST_MATCH_TOLERANCE = 0.02  # 2% |recorded - recomputed| / recomputed


@dataclass(frozen=True)
class CostFinding:
    check: str
    label: str
    detail: str


@dataclass(frozen=True)
class CostAuditResult:
    ok: bool
    rows: int
    findings: tuple[CostFinding, ...]
    output_path: Path | None = None


# --- world 1: comparison.csv (obviousbench shape) --------------------------


def audit_comparison_costs(
    comparison_path: Path,
    *,
    selection_audit_path: Path | None = None,
    output_path: Path | None = None,
    low_usd_per_mtok: float = DEFAULT_LOW_USD_PER_MTOK,
    full_rerun_sources: frozenset[str] = DEFAULT_FULL_RERUN_SOURCES,
    required_repair_dir_substring: str = "cumulative-cost-runs",
    title: str = "Cost Integrity Audit",
) -> CostAuditResult:
    """Audit comparison costs for silently missing or partial accounting."""
    rows = _read_csv(comparison_path)
    findings: list[CostFinding] = []
    for row in rows:
        label = row.get("label") or row.get("model") or "<unknown>"
        scored_samples = _int(row.get("scored_samples"))
        provider_errors = _int(row.get("provider_errors"))
        timeouts = _int(row.get("timeouts"))
        successful_samples = max(scored_samples - provider_errors - timeouts, 0)
        total_tokens = _float(row.get("total_tokens"))
        estimated_cost = _float(row.get("estimated_cost_usd"))
        cost_warnings = (row.get("cost_warnings") or "").strip()

        if cost_warnings:
            findings.append(CostFinding("cost_warning", label, cost_warnings))
        if successful_samples > 0 and total_tokens == 0:
            findings.append(
                CostFinding(
                    "missing_usage_telemetry",
                    label,
                    (
                        f"{successful_samples} successful sample(s) but total_tokens=0 "
                        "and estimated_cost_usd=0"
                    ),
                )
            )
        if total_tokens > 0 and estimated_cost == 0 and not _looks_free(row):
            findings.append(
                CostFinding(
                    "nonzero_tokens_zero_cost",
                    label,
                    f"total_tokens={_format_number(total_tokens)} but estimated_cost_usd=0",
                )
            )
        if total_tokens > 0 and estimated_cost > 0 and not _looks_free(row):
            usd_per_mtok = estimated_cost / total_tokens * 1_000_000
            if usd_per_mtok < low_usd_per_mtok:
                findings.append(
                    CostFinding(
                        "suspiciously_low_usd_per_mtok",
                        label,
                        (
                            f"effective price ${usd_per_mtok:.6f}/M tokens is below "
                            f"${low_usd_per_mtok:.6f}/M"
                        ),
                    )
                )

    if selection_audit_path is not None:
        for row in _read_csv(selection_audit_path):
            selected_source = (row.get("selected_source") or "").strip()
            if selected_source in {"", "base"} or selected_source in full_rerun_sources:
                continue
            summary_dir = row.get("summary_dir") or ""
            if required_repair_dir_substring not in summary_dir:
                findings.append(
                    CostFinding(
                        "repair_source_not_cumulative",
                        row.get("label") or row.get("model") or "<unknown>",
                        (
                            f"selected_source={selected_source} points at {summary_dir}; "
                            "repair/cache-hit selections must point at "
                            f"{required_repair_dir_substring}"
                        ),
                    )
                )

    result = CostAuditResult(
        ok=not findings,
        rows=len(rows),
        findings=tuple(findings),
        output_path=output_path,
    )
    if output_path is not None:
        _write_report(output_path, result, title, f"Comparison rows: {result.rows}")
    return result


# --- world 2: run summaries (interactive-runner shape) ----------------------


# How a run's recorded cost was produced (a summary's ``cost_basis``). Rows
# without one are recomputed from their usage totals.
PER_REQUEST_LIST = "per_request_list"  # each request priced at its day's list by the harness
ROUTE_REPORTED = "route_reported"  # an aggregator's own per-request bill (PLAYBOOK section 7)


def audit_summary_costs(
    summaries: Sequence[dict],
    *,
    prices: dict[str, tuple[float, float]] | None = None,
    pricer=None,
    output_path: Path | None = None,
    tolerance: float = DEFAULT_COST_MATCH_TOLERANCE,
    title: str = "Run Summary Cost Integrity Audit",
) -> CostAuditResult:
    """Audit interactive-runner summary dicts (each with 'model',
    'episodes', 'usage', 'cost_usd_list_price'). Pass the vendored pricing
    registry's PRICES as ``prices`` to enable list-price recomputation.

    ``pricer(model, usage, on)`` (optional) recomputes a row's list price on
    its collection day (``row['collected_on']``) with every usage class, and
    takes precedence over the flat ``prices`` table. A row whose
    ``cost_basis`` is ``per_request_list`` was priced request by request by
    its harness, which a run-level recomputation cannot reproduce
    (long-context rates switch per request; failed seeds' partial episodes
    are billed but not stored), so the consumer must audit those requests
    itself; a ``route_reported`` row carries an aggregator's own bill. Both
    skip the recomputation and keep every other check."""
    findings: list[CostFinding] = []
    for index, summary in enumerate(summaries):
        label = str(summary.get("label") or summary.get("model") or f"row{index}")
        episodes = _int(summary.get("episodes"))
        usage = summary.get("usage") or {}
        input_tokens = _int(usage.get("input_tokens"))
        output_tokens = _int(usage.get("output_tokens"))
        total_tokens = input_tokens + output_tokens
        cost = summary.get("cost_usd_list_price")

        if episodes > 0 and total_tokens == 0:
            findings.append(
                CostFinding(
                    "missing_usage_telemetry",
                    label,
                    f"{episodes} episode(s) but usage totals are zero",
                )
            )
        if total_tokens > 0 and (cost is None or _float_of(cost) == 0):
            findings.append(
                CostFinding(
                    "nonzero_tokens_zero_cost",
                    label,
                    f"{total_tokens} tokens but cost_usd_list_price={cost!r}",
                )
            )
        model = summary.get("model")
        recomputed: float | None = None
        if summary.get("cost_basis") in (PER_REQUEST_LIST, ROUTE_REPORTED) or total_tokens == 0:
            recomputed = None
        elif pricer is not None and isinstance(model, str):
            recomputed = pricer(model, dict(usage), summary.get("collected_on"))
        elif prices and isinstance(model, str) and model in prices:
            pin, pout = prices[model]
            recomputed = input_tokens / 1e6 * pin + output_tokens / 1e6 * pout
        if recomputed is not None:
            recorded = _float_of(cost)
            if recomputed > 0 and abs(recorded - recomputed) / recomputed > tolerance:
                findings.append(
                    CostFinding(
                        "cost_not_list_price",
                        label,
                        (
                            f"recorded ${recorded:.4f} vs list-price recomputation "
                            f"${recomputed:.4f} (>{tolerance:.0%} apart) — published "
                            "costs must be undiscounted list"
                        ),
                    )
                )
    result = CostAuditResult(
        ok=not findings,
        rows=len(summaries),
        findings=tuple(findings),
        output_path=output_path,
    )
    if output_path is not None:
        _write_report(output_path, result, title, f"Run summaries: {result.rows}")
    return result


# --- shared ------------------------------------------------------------------


def _write_report(path: Path, result: CostAuditResult, title: str, scope_line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    status = "PASS" if result.ok else "BLOCKED"
    lines = [
        "---",
        f"title: {title}",
        "type: audit",
        f"status: {status.lower()}",
        "---",
        "",
        f"# {title}",
        "",
        f"Overall status: {status}",
        "",
        scope_line,
        f"Findings: {len(result.findings)}",
        "",
        "## Findings",
        "",
    ]
    if result.findings:
        for finding in result.findings:
            lines.append(f"- `{finding.check}`: {finding.label} - {finding.detail}")
    else:
        lines.append("No cost integrity issues found.")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _int(value) -> int:
    return int(_float_of(value))


def _float(value: str | None) -> float:
    if value in {None, ""}:
        return 0.0
    return float(value)


def _float_of(value) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


def _looks_free(row: dict[str, str]) -> bool:
    model = (row.get("model") or "").casefold()
    cost_source = (row.get("cost_source") or "").casefold()
    return model.endswith(":free") or "free" in cost_source


def _format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return str(value)
