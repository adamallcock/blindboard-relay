---
title: Archiving Blindboard Relay
date: 2026-10-04
type: runbook
status: code-archive-published
---

# Archiving Blindboard Relay

The repository includes the code, recorded evidence and paper. The
[v1.0.0 archive](https://doi.org/10.5281/zenodo.23142771) preserves commit
`14161572d8bc7016663b670b1b2f1afdcfc17157`; its
[concept DOI](https://doi.org/10.5281/zenodo.23142770) covers all versions.
Every archived file was verified against the release's checksum inventory.
The current paper and citation files add the DOI assigned at publication;
the archived release remains fixed. A separate paper deposit has prepared
metadata and has not been published. Relay's records are separate from the
released Blindboard base benchmark.

## GitHub integration

Enable `adamallcock/blindboard-relay` in Zenodo before publishing the first
GitHub release. Zenodo uses the root `.zenodo.json` as the code/evidence
record's metadata. Publish the release from the verified commit, then record
the version and concept DOIs returned by Zenodo. Keep the release tag fixed.

## Manual deposits

The `zenodo/` directory contains API request bodies with the required
`metadata` wrapper:

- `zenodo/code-evidence-v1.json` describes the repository archive.
- `zenodo/paper-v1.json` describes the preprint and accompanies `paper/relay.pdf`.

The root `.zenodo.json` and `paper-zenodo.json` contain the corresponding
unwrapped metadata. These files do not create or publish a deposit.

## After the records are published

Add the returned Relay DOIs to the paper's availability statement,
`CITATION.cff`, README and submission metadata. Link the paper and evidence
records to each other. Preserve the base benchmark citations already present
in the metadata. Record the exact archived Git commit and verify the
downloaded archive against its `SHA256SUMS` inventory.

Zenodo's [GitHub guide](https://help.zenodo.org/docs/github/)
and [deposit API](https://developers.zenodo.org/) describe both routes.
