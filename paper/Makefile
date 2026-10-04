# Relay repository: the vendored kit and existing Relay build targets.
ROOT := ..
PY ?= uv run python
.DEFAULT_GOAL := relay-pdf

vendor:
	cd $(ROOT) && $(PY) scripts/check_vendored.py

# ---- Relay paper targets (thin main + sections/; tables from relay_analysis) ----

.PHONY: relay-assets relay-figures relay-gates relay-bib relay-claims relay-pdf \
	relay-redline relay-check relay-bbl

relay-assets:
	cd $(ROOT) && python3 scripts/relay_analysis.py

relay-figures:
	cd $(ROOT) && uv run --with matplotlib python scripts/make_relay_figures.py
	cd $(ROOT) && uv run --with matplotlib python scripts/make_relay_explainer.py

relay-gates:
	cd $(ROOT) && python3 scripts/relay_gates.py

relay-bib:
	cd $(ROOT) && $(PY) scripts/check_bib.py --bib paper/references.bib

relay-claims:
	@! grep -rn --include='*.tex' -E '\\(obtodo|claimblocked)' sections/ relay.tex \
		| grep -Ev '^[^:]+:[0-9]+:[[:space:]]*%' || (printf 'unresolved claim-gate macros above\n' && exit 1)
	@printf 'relay-claims: no unresolved claim-gate macros\n'

relay-pdf: relay-assets relay-figures
	tectonic --keep-logs relay.tex

# arXiv runs no BibTeX: build once in a scratch dir and keep only relay.bbl.
relay-bbl:
	@set -eu; tmp=$$(mktemp -d); trap 'rm -rf "$$tmp"' EXIT; \
	tectonic --keep-intermediates --outdir "$$tmp" relay.tex >"$$tmp/build.log" 2>&1 \
	  || { cat "$$tmp/build.log"; exit 1; }; \
	test -s "$$tmp/relay.bbl"; cp "$$tmp/relay.bbl" relay.bbl; \
	printf 'relay-bbl: wrote relay.bbl\n'

# Redline: REDLINE_BASE (a commit; default HEAD) vs the working tree. The
# base's whole paper/ tree is materialized from git so each side flattens its
# OWN sections/ (flattening the base main file in place diffs the current
# sections against themselves and marks nothing). Fails if the sources differ
# but the diff marks nothing.
REDLINE_BASE ?= HEAD
relay-redline:
	@set -eu; tmp=$$(mktemp -d); held=; \
	trap 'if [ -n "$$held" ]; then mv relay.bbl.held relay.bbl; fi; rm -rf "$$tmp" .redline_diff.tex' EXIT; \
	git -C $(ROOT) archive $(REDLINE_BASE) paper | tar -x -C $$tmp; \
	rm -f "$$tmp/paper/relay.bbl"; \
	held=; if [ -f relay.bbl ]; then mv relay.bbl relay.bbl.held; held=1; fi; \
	latexdiff --flatten --append-safecmd=benchmarkname \
	  --config="PICTUREENV=(?:picture|DIFnomarkup|table|figure|threeparttable|tablenotes|tabular|tabularx)[\w\d*@]*" \
	  $$tmp/paper/relay.tex relay.tex > .redline_diff.tex 2>/dev/null; \
	if [ -n "$$held" ]; then mv relay.bbl.held relay.bbl; held=; fi; \
	marks=$$(grep -oE 'DIF(add|del)\{' .redline_diff.tex | wc -l | tr -d ' '); \
	if ! git -C $(ROOT) diff --quiet $(REDLINE_BASE) -- paper/relay.tex paper/sections \
	   && [ "$$marks" -eq 0 ]; then \
	  printf 'relay-redline: sources differ from %s but the diff marks nothing\n' "$(REDLINE_BASE)"; \
	  rm -rf $$tmp .redline_diff.tex; exit 1; fi; \
	tectonic .redline_diff.tex; \
	base=$$(git -C $(ROOT) rev-parse --short $(REDLINE_BASE)); \
	mv .redline_diff.pdf relay-redline-$$base-to-working.pdf; \
	rm -rf $$tmp .redline_diff.tex; \
	printf 'relay-redline: %s change markers -> relay-redline-%s-to-working.pdf\n' "$$marks" "$$base"

# The only target a relay release decision may cite.
relay-check: vendor relay-bib relay-claims relay-assets relay-gates relay-pdf
	@echo "relay-check: all gates ran; see individual PASS/FAIL lines above"
