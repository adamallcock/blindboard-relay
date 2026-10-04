# Blindboard Relay

Blindboard Relay measures whether a language model can write notes that its
next turn can use. Each turn starts with a fresh model instance. Its rules,
current observation and one budgeted note are its entire context. The earlier
conversation and reasoning are gone.

Four text interfaces compare free-form notes, a supplied schema, a pinned
model-written constitution and a harness-validated form. A pixel channel
passes only a rendered image. A sound reference solver plays through the same
budget, and two transcript controls distinguish visible history from retained
reasoning.

This repository contains the paper, benchmark code and recorded evidence.

## Paper and evidence

Read the [Zenodo preprint](https://doi.org/10.5281/zenodo.23142984)
or the [PDF](paper/relay.pdf). Raw recorded episodes, notes, images,
summaries and calibrations are under [results/relay/](results/relay/).
[`BUNDLE.json`](BUNDLE.json) pins the
source revision and evidence-manifest hash. `SHA256SUMS` hashes every shipped
file; the experiment's narrower selection manifest remains under
`results/relay/MANIFEST.json`.

These measurements use public development seeds at one effort
setting per model, not official held-out scores or an evaluation of deployed
agent memory. Original-model transcript controls differ in collection date;
the paper identifies the same-day fresh-seed replications separately. No
condition collected here establishes an ordering of the strongest models.
The notation-drift metric fails its fixed-codec negative control, so the paper
claims surface stabilization rather than chain-specific convention formation.

## Reproduce without model calls

Python 3.11+ and the standard library suffice for analysis and manifest checks.
Tests need pytest, figures need matplotlib, and the paper build uses Tectonic.
Tectonic supplies the XeLaTeX-compatible font environment used by the paper.
Fresh pixel rendering needs `resvg` or macOS Quick Look. Analysis of the
recorded experiments uses the stored images.

```sh
shasum -a 256 -c SHA256SUMS
python3 scripts/relay_manifest.py
python3 scripts/check_vendored.py
python3 scripts/relay_analysis.py
uv run --with pytest -m pytest -q
make -C paper relay-pdf
```

`python3 rebuild.py` verifies checksums, checks the evidence manifest and
rebuilds numerical macros and analysis byte for byte. Generated release-gate
metadata records the checks performed in the source snapshot; a new
`make -C paper relay-check` runs the repository's gates and refreshes that
table. The historical Quick Look renderer check remains explicitly waived on
other macOS versions. Stored pixels are records; do not silently re-render
historical episodes with another renderer.

Running provider models is optional and billed separately. The collection
entrypoints are `scripts/relay_run.py` and `scripts/relay_svg_run.py`; inspect
their help before making calls. Never use the evidence manifest's `--write`
mode during a reproducibility check.

## Base environment and licence

The `blindboard/` dependency is materialized from the released Blindboard
code, preserving its import paths and licences. Relay never imports a sibling
checkout or a private benchkit package. Its shared infrastructure is pinned
to benchkit 0.3.10 in `.benchkit.json`.

- [Blindboard repository](https://github.com/adamallcock/blindboard)
- [Blindboard paper](https://doi.org/10.5281/zenodo.23121596)
- [Blindboard code and evidence archive](https://doi.org/10.5281/zenodo.23121518)

Code is Apache 2.0; data, documentation and paper are CC BY 4.0, following the
base release. See [LICENSE](LICENSE) and
[LICENSE-DATA-DOCS.md](LICENSE-DATA-DOCS.md).

## Citation and archiving

Use [CITATION.cff](CITATION.cff) to cite the paper or repository. The paper is
*Blindboard Relay: Measuring Model-Written Memory Across Amnesiac Turns*,
by Adam Allcock (2026), published as a
[Zenodo preprint](https://doi.org/10.5281/zenodo.23142984).

The [v1.0.0 code and evidence archive](https://doi.org/10.5281/zenodo.23142771)
preserves commit `14161572d8bc7016663b670b1b2f1afdcfc17157`, including the paper.
The [all-versions DOI](https://doi.org/10.5281/zenodo.23142770) follows the
archive across releases. The current paper and citation files include the
DOI assigned after that archive was published.

[Archiving instructions](docs/2026-10-04-archiving.md) record both publications
and describe future releases. The paper and code/evidence records link to
each other and are separate from the base benchmark.
