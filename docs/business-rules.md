# Business rules

Domain rules for the migration and reconciliation. Pinned before any
pipeline code. Terminology is defined in `CONTEXT.md`; term-level detail and
the mismatch enums are in `docs/definitions.md`.

## Working rules

- Work one ticket at a time.
- No SQL change without a mismatch report first.
- Never invent account codes.
- Never fix totals by editing target amounts.
- SQL is the reconcile engine, not Pandas.
- A green test is not a closed period until `reports/period_YYYY-PP.md` exists.
- Source of truth is the files in this repo.
- Reconciling differences or changing a business rule is careful work. Slow
  down for it.

## GL grain

`company_code + doc_id + line_no + fiscal_period`. Physical columns:
`company_code`, `document_id`, `line_number`, `fiscal_year` +
`fiscal_period`, where a period is the pair, not a calendar month string.

## Scope, first pass

`company_code = 1000`, periods `(2024,01)`, `(2024,02)`, `(2024,03)`.

## Reconciliation baseline

No separate legacy-system file exists, and none is fabricated. Compare
`stg_gl` (raw, as-loaded) against `fact_gl_line` (mapped, deduped,
DQ-checked, period-scoped). See `docs/definitions.md`.

## Money: two different checks, not interchangeable

- Balance validation (is a document publishable) uses
  `debit_amount − credit_amount`.
- Close totals (what is reported to finance) use `local_amount`.
- `local_amount` not netting to zero on an otherwise-balanced document is
  its own finding (`local_amount_imbalance`), not a publish blocker.
- Never sum `transaction_amount` to close a period.

## Doc types

Counted in period close: `SA, DR, KR, DZ, KZ, AA, WE, WL, HR, IC`

Not counted:
- `OPENING_BALANCE`: brought-forward balance. Separate flag, never mixed
  into in-period totals.
- `CL`: closing entry. Not in in-period totals.

Unknown doc type (in neither list): do not count it in the close, set status
`unmapped_doc_type`, do not guess revenue vs expense.

## Unbalanced document

`debit_amount − credit_amount != 0`: load to staging, never publish. Caught
by a check named `unbalanced_document`.

## Flagged rows: is_fraud, is_anomaly, is_post_close

These are reconciliation content, never a filter. Do not write
`WHERE is_fraud = false` or drop anomalous rows to make totals look clean.

- `is_fraud` / `is_anomaly` flow through unchanged. If they cause a
  difference, it goes in the mismatch report with a cause from `fraud_type`
  / `anomaly_type`.
- `is_post_close` is excluded from the in-period close total but reported in
  its own bucket, never deleted.

## Reversals

No `is_cancelled` column exists. Detect reversal documents by convention
(`reference` starts `REV-...`, `header_text` reads "Reversal of
<document_id>"), link to the original, and report as a "reversal pairs"
bucket. Never delete either side.

## Period load

Replacing a period replaces the whole period, never appends. Re-running with
unchanged mapping yields the same totals and row counts.

## Duplicate grain

Blocking violation `duplicate_source`, never auto-dedup. No column in the
source says which copy is "latest." See `docs/definitions.md`.

## Mapping

No real target chart of accounts exists yet. First pass derives one from the
source `account_class` hierarchy (~27 rows). A human approves
`map_account.csv` (`source_account, target_account, status`) before any
reconcile run. `source_account` must be unique; duplicates are a blocking
`map_fanout` error, checked every load. Accounts with no target are marked
`unmapped`. Target account codes are never guessed. They come only from the
approved mapping file.

## Mismatch classification

Every mismatch gets one bucket (symptom) and one cause (reason) from the
fixed lists in `docs/definitions.md`. Never add a new cause in SQL without
adding it there first. `unknown` over 20% of a period's mismatches blocks
sign-off.

## "Done" for every task

A period total (`stg_gl` against `fact_gl_line`, per account, checked to
0.01 tolerance), a count of documents that do not match, and a primary cause
for every gap over 0.01 (not one bucket of `unknown`). The signed-off
deliverable is `reports/period_<period>.md`.
