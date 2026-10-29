# Restricted batch v56

This batch promotes ten current-version cards from `shadow` to `restricted / pre_generation_only` in `rag-catalog-v3-rc4.6`.

The candidate gate requires positive admission, exact `not_needed` handling for known and explicitly inapplicable facts, fail-closed conflict and insufficiency handling, tamper rejection, tokenizer budget, BM25 and remote dense top-five retrieval, shadow blocking, and one immutable current-version control/card model pair per promoted card.

The campaign made 22 generation calls with no retry: 20 calls support the ten promoted cards. Two calls belong to `v9-public-division-equality-boundary`; its card arm produced a compile failure and the card remains shadow. `v9-public-toggle-divider-period` replaced it and passed both arms.

No production cohort, default configuration, online configuration, upload, deployment, commit, or submission is part of this batch.
