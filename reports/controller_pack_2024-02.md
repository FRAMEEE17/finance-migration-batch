# Controller pack: 2024-02

Company 1000, period 02. For sign-off review.

## Risk this period

27 documents this period report a currency total that cannot be trusted[^1]. The figure normally used to close a period is broken for those documents; debit and credit totals are not affected and remain reliable. This is a known, tracked issue, not new this period.

## Decision

- **Reconciliation:** accepted
- **Reported currency total:** not signed

- Documents compared[^2]: **502**, matched exactly: **502**
- Debit/credit gap (the figure to use for this period's judgment): **0.00**

The reconciliation decision and the currency-total decision are not the
same question. A clean reconciliation does not mean the currency total
is correct - both sides of that comparison inherit the same defect.

## Status at a glance

| recon_status | local_amount_status | dc_gap | defect doc count |
|---|---|---|---|
| accepted | not_signed | 0.00 | 27 |

## Still open

Issue #13 (source-data defect, not this pipeline's territory) has to
close before the currency total above can be signed. Full detail is in
the working paper and exception appendix for this period, not repeated
here.

## Sign-off

Reconciliation reviewed and accepted by:

Signed by: _______________  Date: _______________

Currency total: **not signed this period.**

---
[^1]: The defect: a document's grand total is repeated on every debit
line instead of that line's own amount. `local_amount` in the
warehouse; `stg_gl`/`fact_gl_line` are the raw and modeled tables.
[^2]: Compared in `recon_period_summary`, one row per account per
period, in `warehouse.duckdb`.

