RTL Skill / RAG optimization v2 — DEVELOPMENT ONLY
Date: 2026-10-26
Frozen framework: dc32c2fc4ff5d0a489ba27e70809ad9b7387cbb2

Scope and status
---------------
This directory does not change production imports, configurations, card/index locks,
Skill admission statuses, or default routing. It contains an explicit development
adapter, synthetic predicate tests, three candidate Skill bodies, a fixed-retriever
comparison, and a prepared but NOT RUN model pilot. No holdout or balanced60 evaluation
has been performed. Unit/regression tests are not product acceptance.

Historical attribution
----------------------
historical-attribution.json binds request/response/selected-file evidence by hash.
It deliberately does not package raw model thinking or hidden judge assets.

Width candidate: the final response corrected the rotation expressions but introduced
an ANSI port body redeclaration. The checker rejected that draft; the score was for
the retained original. The historical thinking repeatedly revisited unrelated interface
questions before finding the bit-mapping error. This is an observed failure path, not
proof that the Skill alone caused the error.
Combinational candidate: completion reached 16384 tokens with empty final content.
Thinking repeatedly revisited interface width and selector interpretations. The L1
score is the original candidate, not a delivered wrong new implementation.
FSM output: both arms delivered and scored L3; Skill increased total tokens from
3958 to 10835 without observed correctness gain.
FSM protocol: both arms reached the output limit without final content. Both L1
scores are for the original candidate. A final-code correctness comparison is absent.

Candidate body changes
----------------------
width-v2.txt, combinational-v2.txt, fsm-v2.txt are version 2.0.0-dev.1.
They constrain work to the failing expression/cone/transition, use a discriminating
boundary check, preserve compiling interfaces/dependencies, and require final delivery.
They contain no checkpoint identifiers or task-specific answers. They are NOT proven
improvements. A shared delivery/verbosity change is a potential confound; if v2 wins,
add a boundary-only control before attributing gains to domain knowledge.

The pilot uses four previously opened development checkpoints, eight requests total,
alternating control/candidate order, temperature 0, top_p 1, seed 20261025, thinking on,
16384 completion tokens, and one repair call. Both arms use identical current English
base prompts and feedback. Historical Chinese-prompt controls are not reused as a
causal comparator. Report complete delivery, checker acceptance, scored new/old file,
tokens, time and functional result separately. No automatic recovery calls or promotion.

Cloud pilot blocker
-------------------
The attempted archive transfer was rejected by the permission reviewer: the existing
authorization explicitly covers cards/queries, not framework source, candidate RTL
and task prompts. The transfer did NOT occur and the real generation pilot did NOT run.
Additional user authorization is required. Do not route around this restriction.
Only the separately authorized 13 de-identified embedding queries were transmitted.
No model service process, arguments or settings were changed.

Admission v2.1
--------------
admission.py distinguishes structural applicability, explicitly supplied information,
and measured benefit. The last remains not_established even when development-eligible.
The F24 predicate requires bound current-candidate/checker/execution evidence, complete
diagnostics, first noncascade error, lint/xvlog/2026.1/VRFC 10-4982, the comma error,
an actual diagnostic source line and exactly one narrow source witness on that line.
Comments/strings, unsupported macros/escaped names, valid syntax, missing locations,
ambiguous witnesses, stale candidates and unknown versions fail closed. Equivalent
feedback examples/paraphrases suppress the card; uncertain wording also returns empty.
Unrelated correct code in the candidate is not treated as supplied repair advice.
The recognizer is deliberately lexical and narrow: it is NOT a complete SV parser,
proof of root cause, or proof that the model lacks the knowledge. Unrecognized cases
remain empty rather than guessing. Novelty language means only "not explicitly supplied
by the supported feedback recognizers", not universal semantic nonredundancy.

The other 32 cards retain their frozen dispositions. Eleven conditional cards still
lack complete source/specification fact extractors and explicitly return
missing_fact_predicate_not_implemented. Their natural-language missing-fact clauses
have NOT been relabeled as implemented predicates. This work closes the F24 example
contract and exposes the remaining gaps; it does not claim full 32-card admission.

adapter.py connects the proposed decision to the unchanged ranking/packing framework
only when explicitly patched by the development tests. No production import enables it.
F24 remains a separate restricted exact lane without a dense vector; backend tests
must not count this lane as evidence of dense or hybrid superiority.

Retriever comparison
--------------------
13 development queries, 8 families; no holdout queries admitted to analysis.
Same 32 English cards/document vectors, k=5, injection limit=1, RRF k=60.
Historical relevance labels are topical development oracle labels, NOT proof of
marginal knowledge or repair benefit. There are no correct-empty labeled queries in
these 13; negatives are separately exercised by the synthetic admission tests.

                   Recall@5   Top-1 relevant   MRR@5
exact               30.77%        61.54%        0.6154
BM25                84.62%        84.62%        0.8718
dense               88.46%        76.92%        0.8333
hybrid              84.62%        92.31%        0.9231

These are query-weighted metrics on a tiny, reused development set, not independent
family-weighted estimates or statistical evidence of a winner. The historical cached
projection retains constructs; production projection uses constructs:none. We encoded
all 13 production projections against the existing cloud embedding service. Five
query/strategy top-5 orderings changed; the aggregate figures above did not.
Embedding transport+encoding averaged about 471 ms (13 sequential cold/warm-mixed
observations, not an SLA). Reported rank latency excludes encoding and generation.
The query-only data lack bound original source/check executions, so admission is
not evaluable and repair_gain stays null. The evaluator intentionally refuses to
manufacture a positive source witness from labels. Fixed synthetic integration tests
exercise admission/packing separately; they do not demonstrate real model gains.

Expression, routing and joint use
--------------------------------
f24-compact-v2.txt is an expression-only follow-up candidate; the frozen card and its
embedding are unchanged. It is NOT used in the current retriever comparison or pilot.
After the blocked Skill pilot, compare original/compact F24 text under fixed admission
and retrieval. Only then run off/Skill-only/RAG-only/both in a development 2x2, and a
route-shadow review. Rejected Skill statuses and automatic routing remain unchanged.
Do not mix body, card, admission and retrieval changes in one performance comparison.
No vector database, learned router or reranker is introduced.

Reproduction (from repository root; Python 3.12 with project dependencies)
------------------------------------------------------------------------
PYTHONPATH=.:dev/optimization-v2 python -m unittest discover -s dev/optimization-v2 -p 'test_*.py' -v
python -m unittest discover -s tests -v
python dev/optimization-v2/evaluate_retrieval.py
python dev/optimization-v2/evaluate_retrieval.py --runtime-projection
python dev/optimization-v2/run_skill_pilot.py

The final command verifies framework/input identities and makes NO model request.
--run-cloud-pilot is an explicit execution opt-in for an authorized separate cloud copy,
with the existing model/judge dependencies. It must not be run before upload approval.
encode_queries.py makes external requests only if explicitly executed; it refuses to
overwrite its saved cache. Existing caches support network-free comparisons.
