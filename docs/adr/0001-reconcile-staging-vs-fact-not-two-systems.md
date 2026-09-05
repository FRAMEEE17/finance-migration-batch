# Reconcile stg_gl vs fact_gl_line, not two separate system extracts

**Status:** accepted

No legacy-system extract file exists for this dataset, and we will not
fabricate one to get a "before/after" pair. Instead, `stg_gl` (the raw CSV,
loaded verbatim) plays the legacy/left side, and `fact_gl_line` (mapped,
deduped, DQ-checked) plays the target/right side of every reconciliation.

Considered: generating a synthetic "legacy" extract so the project looks like
a classic two-system migration. Rejected: fabricating source data is out
of scope for this project, and a synthetic legacy file would let mismatches
be whatever we wrote them to be, which defeats the point of reconciliation.

Consequence: "recon" in this project answers "what did the pipeline change,
and why," not "does system A match system B." A future engineer joining a
real two-system migration should not assume this project's SQL generalizes
directly. The join keys are the same, but the semantic question is different.
