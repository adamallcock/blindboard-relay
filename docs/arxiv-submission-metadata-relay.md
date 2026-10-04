---
title: arXiv Submission Metadata (relay)
type: review
status: draft
metadata_status: draft
article_title: "Blindboard Relay: Measuring Model-Written Memory Across Amnesiac Turns"
authors:
  - "Adam Allcock (Independent researcher; adamallcock@gmail.com)"
abstract: "Blindboard Relay tests whether language models can write notes that a fresh instance can use on the next turn. In Blindboard, a hidden-keyboard deduction game, each turn receives the fixed rules, one predecessor note and the current observation. The client discards the earlier transcript and reasoning. The score is the fraction of keys identified correctly. A sound reference policy supplies an attainable score at each note budget. We sample combinations of nine models from three providers, seven budgets and four text interfaces, with visible-transcript and retained-reasoning controls. At 100 characters, GPT-5.4 Nano's notes score .503 below its retained-reasoning control (p < .001); these conditions were collected on different dates. A supplied schema improves Nano's notes by .419 at 200 characters and .512 at 50, surviving correction over the declared 24-test family. Schema notes also outperform Nano's visible transcript, but the later retained-reasoning control scores .196 higher than the schema. Same-day tests on fresh seeds confirm higher scores with retained reasoning for GPT-5.6 Luna and GPT-6 Luna. GPT-6 Sol, Gemini 3.8 Flash and Claude Opus 5.5 score at least .969 in every tested condition at 100 characters. Tighter budgets lower their scores but do not establish a ranking. Adjacent note formats become more similar within longer chains, but the metric does not establish chain-specific conventions. These pilot results, at one reasoning effort, support model-specific memory tests. Frontier rankings and transfer to open-world agent memory remain unestablished."
primary_category: "TODO(confirm; template default cs.CL, cs.LG or cs.AI also fit)"
secondary_categories:
  - "cs.AI"
license: "TODO(confirm arXiv license selection)"
comments: "26 pages, 6 figures, 9 tables; benchkit house layout; counts checked October 4, 2026"
repository_url: "https://github.com/adamallcock/blindboard-relay"
dataset_url: "https://github.com/adamallcock/blindboard-relay/tree/main/results/relay"
ai_tool_disclosure: "AI coding and writing tools were used in building the environment and harness and in drafting this manuscript; the instrument audit and all data-collection decisions were made under human direction. The author reviewed all content and takes responsibility for it."
submitter_registered_author: false
endorsement_checked: false
submitter_is_author_or_authorized_proxy: false
title_and_abstract_checked: false
---

# arXiv Submission Metadata (relay)

This draft records metadata for the arXiv upload form; human confirmation remains pending.
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

The abstract is synchronized with the manuscript. Repository, archive, category, licence and submitter confirmations remain pending publication decisions. No Relay DOI has been issued.
