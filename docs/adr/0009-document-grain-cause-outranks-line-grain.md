# When a line fails two blocking checks at once, the document-grain cause wins

**Status:** accepted

`reconcile_mismatch.py` joins `recon_mismatch` rows against `dq_violations`
to fill in a `missing_in_fact` row's cause. A `stg_gl` line can fail more
than one blocking check at the same time - a whole document can be
`unbalanced_document` while one of its lines is separately a
`duplicate_source`. The join matched every check that applied and produced
one output row per match: `CI-DOC-DUP-001` in the CI fixture has 2 physical
`stg_gl` rows for its duplicated line, and `recon_mismatch` logged 4 rows
for it, 2 per matching check. Checked the real dataset (company 1000, 2024
P01-P03): no document there has ever hit two blocking checks at once, so
every signed period report is unaffected. The bug was real, just never
triggered by real data.

Considered: keep multiple rows and let the cause table show both. Rejected
- `docs/definitions.md` and this project's whole mismatch model assume one
row, one cause, per source line. A count of "how many lines are missing"
that's actually counting "how many check-line combinations exist" is wrong
in a way that's easy to miss and would inflate the cause breakdown in
`reports/period_<period>.md` the moment real data ever hit this shape.

Considered: pick a cause with `MIN(check_name)` or some other arbitrary
tie-break. Rejected - alphabetical order has no relationship to which
check is actually the reason the line is missing, and would pick different
"winners" depending on what the check happens to be named.

Decision: a blocking check at document grain always outranks a blocking
check at line grain, which outranks a non-blocking check. The document was
excluded whole, so the document-grain reason is the actual reason every
line in it is missing from `fact_gl_line`, regardless of what else is
independently true about one particular line. Ties inside a tier break by
each check's position in `quality_gate.py`'s own `CHECK_NAMES` tuple - an
order that already exists there, reused rather than invented a second
time. Every check still logs to `dq_violations` regardless of which one
wins the tie; nothing is deleted, only `recon_mismatch`'s single cause
column is affected.

Consequence: adding a new blocking check later means deciding its grain
(document or line) up front, since that decision now determines its
priority against every other check without further code changes. A new
document-grain blocking check would need to be checked against this
ordering explicitly, not assumed to slot in safely.
