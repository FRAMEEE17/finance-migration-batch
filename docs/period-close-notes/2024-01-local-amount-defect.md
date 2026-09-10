# 2024-01: local_amount cannot close the period as-is

**Status:** known issue, escalated from Ticket 6. For `reports/period_2024-01.md` (Ticket 9) to disclose, not for this note to resolve.

The period cannot be closed using `local_amount` as it stands. The discrepancy is **97,144,587.1**, coming from **20 documents**. The largest one distributes the document's total across every debit line instead of giving each line its own amount.

## What was checked

Two hypotheses, both tested with queries before any transform (see `notebooks/06-account-level-reconciliation.ipynb`):

1. **The ledger doesn't balance on debit/credit.** Rejected. The gap across the whole P01 scope is `90.0`, exactly the 1 document already excluded as `unbalanced_document`. Everything else balances correctly.
2. **`local_amount` is broken on specific documents.** Confirmed. 20 documents, each with an unusually high line count (18-81 lines, versus 2-4 typical), account for the entire period net. The largest: 36 debit lines, each carrying a different `debit_amount`, but every one shows the identical `local_amount` value (`1,189,904.91`), which is the *document's total*, not that line's own amount. The single credit line correctly shows the negative total. This reads as the document total being broadcast onto every debit line during source generation, not currency-conversion rounding.

## Where this shows up

- `dq_violations`, `check_name='local_amount_imbalance'`: 23 rows (20 of them this defect, 3 genuine sub-cent rounding).
- `recon_period_summary.imbalanced_local_amount`, summed across all accounts: `97,144,587.1`.
- The `stg_gl` vs `fact_gl_line` comparison itself stays clean (only 2 accounts show any gap, both from the 1 unbalanced document): `fact_gl_line` inherits the same `local_amount` values `stg_gl` has, defect included, because nothing in Ticket 4 or 5 touches that column.

## What this note is not

Not a fix. `stg_gl` is raw and immutable; a "corrected" `local_amount` in `fact_gl_line` would be editing a target amount, which `docs/business-rules.md` rules out without a separate, explicit decision. Root-cause investigation into how the source dataset generates `local_amount` for high-line-count documents is tracked separately (see the source-data ticket this note references once filed), not attempted here.
