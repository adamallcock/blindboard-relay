#!/usr/bin/env python3
"""Consumer audit runner for this repo's papers (blindboard.tex, relay.tex).

Thin CLI over the VENDORED benchkit paper-audit modules (scripts/*_kit.py;
see .benchkit.json) — this repo never imports benchkit itself. Every
subcommand prints a gate-style PASS/FAIL report and exits nonzero on any
hard failure, so the paper/Makefile targets compose into `release-check`,
the only target a release decision may cite.

Per-paper configuration (required figures, bundle members, metadata note,
frozen-evidence files) lives here so the Makefile stays thin.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import build_paper_assets as bpa  # noqa: E402 (this repo's asset builder)
from arxiv_bundle_kit import (  # noqa: E402 (vendored)
    DEFAULT_EXCLUDE_SUFFIXES,
    ArxivBundleAuditInputs,
    audit_arxiv_bundle,
    build_arxiv_bundle,
)
from arxiv_metadata_kit import (  # noqa: E402 (vendored)
    ArxivMetadataInputs,
    build_submission_metadata_template,
)
from check_vendored import check_consumer  # noqa: E402 (vendored)
from claims_kit import audit_claims, build_claim_ledger  # noqa: E402 (vendored)
from cost_integrity_kit import audit_summary_costs  # noqa: E402 (vendored)
from gates_kit import GateResult  # noqa: E402 (vendored)
from pdf_audit_kit import PdfAuditInputs, audit_paper_pdf  # noqa: E402 (vendored)
from preflight_kit import PreflightInputs, build_preflight  # noqa: E402 (vendored)
from source_audit_kit import SourceAuditInputs, audit_paper_source  # noqa: E402 (vendored)

PAPER_DIR = ROOT / "paper"


@dataclass(frozen=True)
class PaperConfig:
    name: str
    main_tex: str
    # pdf_audit: the standalone figure files this paper cannot ship without.
    # MUST be non-empty (require_figures=True): the kit's prove-it-looked rule
    # forbids an empty list silently passing as "figures checked".
    required_figures: tuple[str, ...]
    # arxiv bundle: what gets packed (relative to paper/) and what the audit
    # must find inside the tar. benchkit.sty is vendored and \usepackage'd by
    # both preambles, so it is required cargo, not an optional extra.
    bundle_members: tuple[str, ...]
    bundle_required_members: tuple[str, ...]
    bundle_required_prefixes: tuple[str, ...]
    # cost integrity: run-summary files backing this paper's cost claims.
    summaries_glob: str
    # human-confirmed submission metadata note (flat docs/ convention).
    metadata_note: str
    # frozen evidence the preflight requires to exist (name -> repo-relative path).
    # NOTE: a held-out SECRET must never appear here. Requiring the secret to
    # exist is the inverse of the gate a release needs (see K3): it blesses a
    # burned answer key. Secrets are covered by secret_object_patterns and
    # seed_digest_candidates below.
    preflight_required_files: dict[str, str]
    # release security. Any git object whose path matches one of these patterns
    # ANYWHERE in history fails the preflight: a seed list that was ever
    # committed is public forever and cannot back a held-out evaluation.
    secret_object_patterns: tuple[str, ...] = ()
    # The published DIGEST of the held-out material. This -- not the secret --
    # is what the release must ship, so a rotated-out list stays verifiable
    # after reveal. Any one candidate satisfies the gate.
    seed_digest_candidates: tuple[str, ...] = ()
    # cost integrity: the run-directory tree, so the audit also sees runs that
    # completed episodes but never wrote a summary.json.
    runs_root: str | None = None
    # extra run trees priced alongside runs_root (campaign arms).
    extra_runs_roots: tuple[str, ...] = field(default_factory=tuple)

    @property
    def stem(self) -> str:
        return Path(self.main_tex).stem

    @property
    def default_bundle(self) -> Path:
        return PAPER_DIR / f"{self.stem}-src.tar.gz"


PAPERS: dict[str, PaperConfig] = {
    "blindboard": PaperConfig(
        name="blindboard",
        main_tex="blindboard.tex",
        required_figures=(
            "figA_walkthrough.pdf",
            "fig_load_profile.pdf",
            "fig2_deducible_converted.pdf",
            "fig4_harness_deltas.pdf",
            "figA_modes.pdf",
            "fig_load_curves.pdf",
        ),
        # Exactly what blindboard.tex inputs: paper/figures and paper/tables
        # also hold the companion Relay paper's files and unused figures,
        # which must not ship with this paper.
        bundle_members=(
            "blindboard.tex", "references.bib", "benchkit.sty",
            "figures/figA_walkthrough.pdf", "figures/fig_load_profile.pdf",
            "figures/fig2_deducible_converted.pdf", "figures/fig4_harness_deltas.pdf",
            "figures/figA_modes.pdf", "figures/fig_load_curves.pdf",
            "tables/snapshot_macros.tex", "tables/cell_macros.tex", "tables/boards.tex",
            "tables/cell_grid.tex", "tables/cell_grid_legacy.tex", "tables/effort_sweep.tex",
            "tables/harness_comparison.tex", "tables/retention.tex", "tables/tiers.tex",
            "tables/usage.tex",
        ),
        bundle_required_members=("blindboard.tex", "references.bib", "benchkit.sty"),
        bundle_required_prefixes=("figures/", "tables/"),
        summaries_glob="results/retained/*/summary.json",
        metadata_note="docs/arxiv-submission-metadata-blindboard.md",
        # The frozen snapshot manifest IS the release object: it names every
        # run dir, included or excluded, with hashes and a generator commit.
        # The burned official_seeds_v1.json is deliberately NOT listed.
        preflight_required_files={
            "frozen snapshot manifest": "paper/snapshot_manifest.json",
        },
        secret_object_patterns=("official_seeds",),
        seed_digest_candidates=("docs/SEED_HASHES.md", "private/SEED_HASHES.md"),
        runs_root="results/retained",
        extra_runs_roots=("results/llm", "results/fragments", "results/robustness"),
    ),
    "relay": PaperConfig(
        name="relay",
        main_tex="relay.tex",
        required_figures=(
            "relay_figA_loop.pdf",
            "relay_figA_regimes.pdf",
            "relay_fig1_knee.pdf",
            "relay_fig2_svg_notes.pdf",
            "relay_fig3_crossover.pdf",
            "relay_fig4_models.pdf",
            "relay_fig5_frontier.pdf",
        ),
        # Exactly what relay.tex inputs, plus the .bbl arXiv needs (it runs no
        # BibTeX; `make -C paper relay-bbl` writes it): paper/figures and
        # paper/tables also hold the Blindboard paper's files.
        bundle_members=(
            "relay.tex", "relay.bbl", "references.bib", "benchkit.sty",
            "sections/01_introduction.tex", "sections/02_related_work.tex",
            "sections/03_environment.tex", "sections/04_certification.tex",
            "sections/05_setup.tex", "sections/06_results.tex", "sections/07_discussion.tex",
            "sections/08_limitations_ethics_reproducibility.tex", "sections/09_conclusion.tex",
            "sections/appendix.tex",
            "figures/relay_figA_loop.pdf", "figures/relay_figA_regimes.pdf",
            "figures/relay_fig1_knee.pdf", "figures/relay_fig2_svg_notes.pdf",
            "figures/relay_fig3_crossover.pdf", "figures/relay_fig4_models.pdf",
            "figures/relay_fig5_frontier.pdf",
            "tables/relay_macros.tex", "tables/relay_audit.tex", "tables/relay_drift.tex",
            "tables/relay_ladder.tex", "tables/relay_contrasts.tex", "tables/relay_families.tex",
            "tables/relay_added.tex", "tables/relay_frontier.tex", "tables/relay_gates.tex",
            "tables/relay_cells.tex", "tables/relay_drift_example.tex",
        ),
        bundle_required_members=("relay.tex", "relay.bbl", "references.bib", "benchkit.sty"),
        bundle_required_prefixes=("figures/", "tables/"),
        # Relay run summaries do not record usage/cost telemetry (the audit
        # will say so loudly); the cost gate in release-check is blindboard's.
        summaries_glob="results/relay/llm/*/summary.json",
        metadata_note="docs/arxiv-submission-metadata-relay.md",
        preflight_required_files={
            "relay calibration certificate": "results/relay/calibration/calibration-codecv2.json",
        },
    ),
}


def _emit(ok: bool, name: str, summary: str) -> None:
    print(f"{'PASS' if ok else 'FAIL':6s} {name} — {summary}")


def _emit_checks(checks, prefix: str) -> None:
    for check in checks:
        _emit(check.status == "pass", f"{prefix}: {check.name}", check.evidence)


# --- release-security gates --------------------------------------------------

SHA256_RE = re.compile(r"\b[0-9a-f]{64}\b")


def git_history_paths() -> tuple[list[str] | None, str]:
    """Every path ever reachable from any ref, via `git rev-list --objects --all`.

    Returns (paths, note); paths is None when git could not be consulted, which
    is itself a gate failure -- an unverifiable history is not a clean one.
    """
    try:
        done = subprocess.run(
            ["git", "rev-list", "--objects", "--all"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover - env dependent
        return None, f"could not run git rev-list: {exc}"
    if done.returncode != 0:
        return None, f"git rev-list exited {done.returncode}: {done.stderr.strip()[:200]}"
    paths = []
    for line in done.stdout.splitlines():
        _sha, _, path = line.partition(" ")
        if path:
            paths.append(path)
    return paths, f"{len(paths)} object path(s) scanned"


def gate_no_secret_in_git_history(cfg: PaperConfig) -> GateResult:
    """FAIL if any held-out seed blob is reachable anywhere in git history.

    This is the inversion of the old preflight behaviour, which REQUIRED
    private/official_seeds_v1.json to exist and marked its presence PASS. A
    seed list that has ever been committed is public forever: replaying it
    turns official evaluation into an answer key. The gate a release needs is
    the opposite one -- prove the secret is NOT reachable.
    """
    name = "held-out seeds absent from git history"
    paths, note = git_history_paths()
    if paths is None:
        return GateResult(name, False, f"history not verifiable ({note}).")
    hits = sorted(
        {
            path
            for path in paths
            for pattern in cfg.secret_object_patterns
            if pattern in path
        }
    )
    if hits:
        return GateResult(
            name,
            False,
            f"{len(hits)} seed object(s) reachable in git history: "
            f"{', '.join(hits[:5])}"
            + (f" (+{len(hits) - 5} more)" if len(hits) > 5 else "")
            + ". Those lists are burned; cut a new list through a never-tracked "
            "process and publish only its digest.",
        )
    return GateResult(
        name,
        True,
        f"no object path matches {list(cfg.secret_object_patterns)} ({note}).",
    )


def gate_seed_digest_published(cfg: PaperConfig) -> GateResult:
    """PASS when a published seed/salt DIGEST file exists and carries at least
    one sha256. The digest is the artifact a release owes third parties -- it
    makes a rotated-out list verifiable after reveal. The secret list itself is
    never required to exist."""
    name = "published seed/salt digest"
    checked = []
    for candidate in cfg.seed_digest_candidates:
        path = ROOT / candidate
        checked.append(candidate)
        if not path.exists():
            continue
        digests = SHA256_RE.findall(path.read_text(encoding="utf-8"))
        if not digests:
            return GateResult(
                name,
                False,
                f"{candidate} exists but contains no sha256 digest — an empty "
                "digest file must not pass as a published digest.",
            )
        return GateResult(
            name, True, f"{candidate} publishes {len(digests)} seed-list digest(s)."
        )
    return GateResult(
        name,
        False,
        f"no digest file found (looked for: {', '.join(checked)}). Publish the "
        "seed-list hash, not the seed list.",
    )


# --- subcommands -------------------------------------------------------------


def cmd_claims(_args) -> int:
    result = audit_claims(PAPER_DIR)
    _emit(
        result.ok,
        "claims (paper/**.tex)",
        f"{len(result.markers)} unresolved marker(s): "
        f"{result.claimblocked_count} claimblocked, {result.obtodo_count} obtodo",
    )
    for marker in result.markers:
        print(f"       {marker.path.relative_to(PAPER_DIR)}:{marker.line_number} "
              f"\\{marker.marker}: {marker.line[:120]}")
    return 0 if result.ok else 1


def cmd_claim_ledger(_args) -> int:
    result = build_claim_ledger(PAPER_DIR)
    _emit(
        result.ok,
        "claim ledger (editorial guidance)",
        f"{result.blocked_count} blocked entr(y/ies); the claims audit is the hard gate",
    )
    for entry in result.entries:
        print(f"       {entry.path}:{entry.line_number} [{entry.category}] {entry.marker_text[:100]}")
    return 0  # guidance, never a gate


def cmd_source_audit(args) -> int:
    cfg = PAPERS[args.paper]
    result = audit_paper_source(
        SourceAuditInputs(
            paper_dir=PAPER_DIR,
            main_tex=cfg.main_tex,
            title=f"Paper Source Audit ({cfg.name})",
        )
    )
    _emit_checks(result.checks, f"source-audit[{cfg.name}]")
    _emit(result.ok, f"source-audit[{cfg.name}]",
          f"{result.passed_count} passed, {result.failed_count} failed")
    return 0 if result.ok else 1


def cmd_pdf_audit(args) -> int:
    cfg = PAPERS[args.paper]
    result = audit_paper_pdf(
        PdfAuditInputs(
            paper_dir=PAPER_DIR,
            main_tex=cfg.main_tex,
            required_figures=cfg.required_figures,
            require_figures=True,  # an empty figure list must never pass silently
            title=f"Paper PDF Build Audit ({cfg.name})",
        )
    )
    _emit_checks(result.checks, f"pdf-audit[{cfg.name}]")
    _emit(result.ok, f"pdf-audit[{cfg.name}]",
          f"{result.passed_count} passed, {result.failed_count} failed")
    return 0 if result.ok else 1


def cmd_arxiv_package(args) -> int:
    cfg = PAPERS[args.paper]
    out = Path(args.out) if args.out else cfg.default_bundle
    # A file the config names explicitly ships whatever its suffix: arXiv
    # runs no BibTeX, so a listed .bbl must survive the build-product filter.
    named = {Path(m).suffix.lower() for m in cfg.bundle_members if Path(m).suffix}
    exclude = tuple(s for s in DEFAULT_EXCLUDE_SUFFIXES if s == ".pdf" or s not in named)
    archived = build_arxiv_bundle(PAPER_DIR, out, members=cfg.bundle_members,
                                  exclude_suffixes=exclude)
    _emit(True, f"arxiv-package[{cfg.name}]", f"{len(archived)} member(s) -> {out}")
    return 0


def cmd_arxiv_audit(args) -> int:
    cfg = PAPERS[args.paper]
    bundle = Path(args.bundle) if args.bundle else cfg.default_bundle
    result = audit_arxiv_bundle(
        ArxivBundleAuditInputs(
            bundle_path=bundle,
            required_members=cfg.bundle_required_members,
            required_prefixes=cfg.bundle_required_prefixes,
            title=f"arXiv Source Bundle Audit ({cfg.name})",
        )
    )
    _emit(result.ok, f"arxiv-audit[{cfg.name}]",
          f"{len(result.members)} member(s), {result.issue_count} issue(s)")
    for issue in result.issues:
        print(f"       {issue}")
    return 0 if result.ok else 1


def cmd_metadata(args) -> int:
    cfg = PAPERS[args.paper]
    out = Path(args.out) if args.out else ROOT / cfg.metadata_note
    if out.exists():  # never overwrite the human-confirmed note
        _emit(True, f"metadata[{cfg.name}]", f"note exists, left untouched: {out}")
        return 0
    build_submission_metadata_template(
        ArxivMetadataInputs(
            output_path=out,
            title=f"arXiv Submission Metadata ({cfg.name})",
        )
    )
    _emit(True, f"metadata[{cfg.name}]",
          f"draft note written (human must confirm before preflight passes): {out}")
    return 0


def cmd_preflight(args) -> int:
    cfg = PAPERS[args.paper]
    bundle = Path(args.bundle) if args.bundle else cfg.default_bundle
    vendor_report = check_consumer(ROOT)
    gate_results = [
        GateResult(
            "vendored infrastructure drift (benchkit)",
            vendor_report.ok,
            vendor_report.summary(),
        )
    ]
    # Release security. Declared per paper: a paper with no held-out material
    # declares no patterns and gets neither gate, rather than a vacuous PASS.
    if cfg.secret_object_patterns:
        gate_results.append(gate_no_secret_in_git_history(cfg))
    if cfg.seed_digest_candidates:
        gate_results.append(gate_seed_digest_published(cfg))
    result = build_preflight(
        PreflightInputs(
            paper_dir=PAPER_DIR,
            bundle_path=bundle,
            output_path=ROOT / "docs" / f"arxiv-preflight-{cfg.name}.md",
            pdf_path=PAPER_DIR / f"{cfg.stem}.pdf",
            gate_results=gate_results,
            required_files={
                name: ROOT / path for name, path in cfg.preflight_required_files.items()
            },
            metadata_confirmation_path=ROOT / cfg.metadata_note,
            bundle_required_members=cfg.bundle_required_members,
            bundle_required_prefixes=cfg.bundle_required_prefixes,
            title=f"arXiv Submission Checklist ({cfg.name})",
        )
    )
    _emit_checks(result.checks, f"preflight[{cfg.name}]")
    _emit(result.ok, f"preflight[{cfg.name}]",
          f"{result.passed_count} passed, {result.failed_count} failed "
          f"-> {result.output_path}")
    return 0 if result.ok else 1


def _reconstructed_summary(record) -> dict:
    """A summary-shaped row rebuilt from a run dir's episode files.

    A run that completed episodes but died before writing summary.json is real,
    already-paid-for evidence. Globbing */summary.json made the cost audit
    blind to exactly those directories, so a "total" could omit them and still
    pass (M5). Reconstructing the row puts them back in front of the auditor.
    """
    usage = {"input_tokens": 0, "output_tokens": 0}
    for path in record.seed_paths:
        result = json.loads(path.read_text(encoding="utf-8"))["result"]
        episode_usage = result.get("usage") or {}
        usage["input_tokens"] += episode_usage.get("input_tokens") or 0
        usage["output_tokens"] += episode_usage.get("output_tokens") or 0
    cost = bpa.usage_cost(record.model, usage)
    return {
        "label": f"{record.tree}/{record.name} [reconstructed: no summary.json]",
        "model": record.model,
        "tier": record.tier,
        "effort": record.effort,
        "episodes": len(record.seed_paths),
        "usage": usage,
        "cost_usd_list_price": cost,
    }


def cost_audit_rows(cfg: PaperConfig) -> tuple[list[dict], list[str]]:
    """Every priceable run backing this paper's cost claims, summarized or not.

    Returns (rows, problems). Model ids are normalized to their pricing-registry
    key so the kit's list-price recomputation actually binds on every route --
    a summary saying 'claude-opus-4-8' does not match the registry's
    'anthropic/claude-opus-4-8', and an unmatched row is silently skipped.
    """
    rows: list[dict] = []
    problems: list[str] = []
    roots = [cfg.runs_root, *cfg.extra_runs_roots] if cfg.runs_root else []

    if roots:
        for root in roots:
            for record in bpa.scan_run_dirs(ROOT / root):
                if record.has_summary:
                    row = dict(record.summary)
                    row.setdefault("label", f"{record.tree}/{record.name}")
                else:
                    if record.model is None:
                        problems.append(
                            f"{record.tree}/{record.name}/ has no summary.json and "
                            "its directory name does not identify a model, so its "
                            f"{len(record.seed_paths)} episode(s) cannot be priced."
                        )
                        continue
                    row = _reconstructed_summary(record)
                rows.append(row)
    else:  # papers that declare only a summaries glob (e.g. relay)
        for path in sorted(ROOT.glob(cfg.summaries_glob)):
            row = json.loads(path.read_text(encoding="utf-8"))
            row.setdefault("label", path.parent.name)
            rows.append(row)

    for row in rows:
        key = bpa.pricing_key(row.get("model"))
        if key is not None:
            row["model"] = key
    return rows, problems


def cmd_cost_audit(args) -> int:
    cfg = PAPERS[args.paper]
    from blindboard.pricing import PRICES  # vendored registry (list prices)

    rows, problems = cost_audit_rows(cfg)
    if not rows:
        _emit(False, f"cost-audit[{cfg.name}]",
              f"no runs found under {cfg.runs_root or cfg.summaries_glob}")
        return 1
    reconstructed = sum(1 for row in rows if "reconstructed" in str(row.get("label")))
    result = audit_summary_costs(rows, prices=PRICES)
    ok = result.ok and not problems
    _emit(ok, f"cost-audit[{cfg.name}]",
          f"{result.rows} run(s) priced ({reconstructed} reconstructed from "
          f"episodes with no summary.json), {len(result.findings) + len(problems)} finding(s)")
    for problem in problems:
        print(f"       unpriceable_run: {problem}")
    for finding in result.findings[:10]:
        print(f"       {finding.check}: {finding.label} — {finding.detail}")
    if len(result.findings) > 10:
        print(f"       ... {len(result.findings) - 10} more finding(s)")
    return 0 if ok else 1


def cmd_report(args) -> int:
    """Combined gate-style report: claims + source + pdf + cost for one paper."""
    print(f"== paper audit report: {args.paper} ==")
    codes = [
        cmd_claims(args),
        cmd_source_audit(args),
        cmd_pdf_audit(args),
        cmd_cost_audit(args),
    ]
    ok = not any(codes)
    _emit(ok, f"report[{args.paper}]", "all audits pass" if ok else "at least one audit failed")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="paper_audits.py", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name, func, *, paper=True, bundle=False, out=False):
        cmd = sub.add_parser(name)
        if paper:
            cmd.add_argument("--paper", choices=sorted(PAPERS), default="blindboard")
        if bundle:
            cmd.add_argument("--bundle", default=None)
        if out:
            cmd.add_argument("--out", default=None)
        cmd.set_defaults(func=func)

    add("claims", cmd_claims, paper=False)
    add("claim-ledger", cmd_claim_ledger, paper=False)
    add("source-audit", cmd_source_audit)
    add("pdf-audit", cmd_pdf_audit)
    add("arxiv-package", cmd_arxiv_package, out=True)
    add("arxiv-audit", cmd_arxiv_audit, bundle=True)
    add("metadata", cmd_metadata, out=True)
    add("preflight", cmd_preflight, bundle=True)
    add("cost-audit", cmd_cost_audit)
    add("report", cmd_report)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
