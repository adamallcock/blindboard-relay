# Blindboard Relay release policy

This repository publishes the Relay protocol, deterministic reference,
recorded model episodes, notes, stored images and analysis used in the paper.
The reported experiments use public development seeds. They are not official
held-out evaluations.

Private evaluation seeds, salts, credentials and development conversation
logs are excluded from this repository. The base benchmark's
[release policy](https://github.com/adamallcock/blindboard/blob/main/docs/release-policy.md)
describes its separate held-out evaluation and commit-reveal procedure.

`BUNDLE.json` identifies the source revision and experiment-manifest hash.
`SHA256SUMS` covers every file in the exported release. Verify both before
regenerating artifacts; never repin the experiment manifest to make a
verification pass. Stored image bytes define the historical pixel channel.
Rendering the same SVG on another platform may produce different pixels.

Code is Apache 2.0. Data, documentation and the paper are CC BY 4.0. Published
release tags remain fixed; changes to code, evidence or the paper require a
new version. Zenodo records retain their own version and concept DOIs.
