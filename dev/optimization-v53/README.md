# Batch 53: first ten-card restricted promotion gate

This batch evaluates the ten current rc4.2 shadow cards that already have a
published pre-generation predicate and current-version no-regression evidence.
It does not change activation state by itself.

`route53.py` uses the current checked-in rc4.2 assets and the hash-pinned
embedding services on the two cloud hosts.  For each card it checks BM25 and
dense top-five retrieval, the actual production admission implementation, and
the common known/conflicting/insufficient/tampered rejection boundaries.
Shadow state is expected to block actual injection during this gate.

Promotion remains per card.  A failed card stays shadow and does not prevent a
different card from being released.
