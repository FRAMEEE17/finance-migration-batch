# Definitions

Every term below was pinned during scoping before any pipeline code.

## Reconciliation baseline

No separate legacy-system extract exists. We do not fabricate one. Both
sides of the comparison are the same data at different stages of one
pipeline:

- **legacy / left side** = `stg_gl`. The raw CSV loaded as-is. No mapping,
  no dedup, no period logic. A copy of what arrived.
- **target / right side** = `fact_gl_line`. One row per publishable account
  line, after mapping, the duplicate-grain guard, DQ, and period logic have
  run. There is no dedup transform. See "Duplicate grain" below.

Reconciliation compares `stg_gl` against `fact_gl_line` per period and per
account. Every row `stg_gl` has that `fact_gl_line` does not, and every
changed amount, must have a named cause. Nothing goes missing without one.

## fiscal_period

A period is the pair `(fiscal_year, fiscal_period)`, not a calendar month
string. `posting_date` is not the period filter. A document's posting date
and its fiscal period can disagree.

**Allowed periods, first pass:**
- `company_code = 1000`
- `(2024, 01)`
- `(2024, 02)`
- `(2024, 03)`

Every loader and every recon query filters on this exact set. Other periods
may land in `stg_gl` but are not reconciled yet.

**FY2025 P02 (2 rows):** out of close scope for this pass. Not counted, not
reconciled, not in `reports/period_2024-*.md`. Kept in `stg_gl` and never
deleted from source. It is a late-arrival fixture for a later ticket, opened
only after the FY2024 P01-P03 reports are signed off and the loader is
stable on re-run. Late data is still valid data. It is just not in scope
this quarter.

## document / line

- **header** = one document (`document_id`).
- **line** = one row within a document (`line_number`).
- **grain** = `company_code + document_id + line_number + (fiscal_year, fiscal_period)`.

## local_amount / balancing basis

`local_amount` is the company's home-currency amount. Used for **close
totals** (what gets reported to finance).

`debit_amount − credit_amount` is used for **balance validation** (whether a
document is publishable). In the FY2024 P01-P03 / company `1000` slice,
`debit − credit` nets to zero for all but 1 of 10,939 documents.
`local_amount` fails to net to zero for 86 documents, from independent
rounding in the currency conversion. The two checks are not interchangeable.

## balanced document

`sum(debit_amount) − sum(credit_amount)` over all lines of one document = 0.
A gap of even 0.01 means not balanced. Status `unbalanced_document`, staging
only, never published.

`local_amount` not netting to zero on an otherwise-balanced document is a
separate finding. Flag `local_amount_imbalance`, and do not block
publication on it.

## balanced period

`sum(local_amount)` over publishable documents, per
`company_code + fiscal_year + fiscal_period` = 0. Excludes `OPENING_BALANCE`,
`CL`, and any document with `is_post_close = true`.

## doc_type catalog

| doc_type | meaning | include_in_close |
|---|---|---|
| OPENING_BALANCE | opening balance | no |
| CL | closing | no |
| SA | manual journal | yes |
| DR | customer invoice | yes |
| KR | vendor invoice | yes |
| DZ | customer payment | yes |
| KZ | vendor payment | yes |
| AA | asset posting | yes |
| WE | goods receipt | yes |
| WL | goods issue / delivery | yes |
| HR | payroll / HR posting | yes |
| IC | intercompany | yes |

All 12 doc types are covered. Any doc type outside this table gets status
`unmapped_doc_type`. It is not counted in the close, and not guessed.

## Flagged rows: is_fraud / is_anomaly / is_post_close

These are source-planted defects. They are reconciliation content and are
never silently filtered.

- `is_fraud = true`, `is_anomaly = true`: these flow through the pipeline
  unchanged. If they cause a difference, that difference goes in the
  mismatch report with a cause drawn from `fraud_type` / `anomaly_type`.
  Never write `WHERE is_fraud = false` to "clean" data.
- `is_post_close = true`: excluded from the in-period close total, and not
  deleted. Reported in its own bucket with count, amount, and document list.

## Duplicate grain (no auto-dedup)

There is no `updated_at`, `source_seq`, or version number in the source to
decide which copy of a duplicate row is "latest." Scope currently has zero
duplicate grains (`transaction_id` is unique across all 40,386 rows). The
rule below is a guard for the future.

- Duplicate grain means the same `company_code + document_id + line_number +
  fiscal_year + fiscal_period` appears more than once.
- On detection: a blocking DQ violation named `duplicate_source`. Publish
  stops for that period. Report the row count and the `document_id`s.
- Never auto-pick a "latest" row (not by `posting_date`, not by
  `transaction_id`, not by row order). Guessing an ordering that does not
  exist in the source risks keeping the wrong version of a corrected
  document. A human decides which copy is real.
- `transaction_id` being unique today shows there is no duplicate problem
  right now. It is not a proxy for "which row is newest" and must never be
  used as one.

Keep these four apart. Each has its own bucket and cause, and none goes
through a dedup function:

| Concept | What it is | doc_id |
|---|---|---|
| Duplicate grain | the same row appearing twice | same |
| Reversal | a new document reversing an old one | different (linked) |
| Post-close | a document in-period but posted after close | same period, own flag |
| Late-arrival | a document outside the current scope | different period |

## Mismatch classification: bucket + cause

Every mismatch has two axes. A row gets exactly one bucket and one cause.
`unknown` is a temporary state. It means the investigation is not finished.

**Bucket** is the symptom (where the difference shows up):

| bucket | meaning |
|---|---|
| `missing_in_fact` | in `stg_gl`, absent from `fact_gl_line` |
| `missing_in_stg` | in `fact_gl_line`, absent from raw (should not happen) |
| `amount_changed` | present both sides, amount differs |
| `intentionally_excluded` | in the warehouse, correctly excluded from the published close total by rule |

**Cause** is the reason. This is the complete list. No other value is valid,
and nothing gets added in SQL without being added here first:

`opening_balance` · `closing_entry` · `post_close` · `unmapped_account` ·
`unmapped_doc_type` · `unbalanced_document` · `duplicate_source` ·
`reversal_pair` · `out_of_scope_period` · `local_amount_imbalance` ·
`rounding` · fraud/anomaly (label = the row's `fraud_type` / `anomaly_type`) ·
`unknown` (temporary only)

**Rules:**

- `intentionally_excluded` pairs only with: `opening_balance`,
  `closing_entry`, `post_close`, `out_of_scope_period`, `reversal_pair`.
- `amount_changed` may use `rounding` only when the gap is at most 0.01. A
  gap over 0.01 needs a real cause.
- `local_amount_imbalance` is not `unbalanced_document`. See the
  balancing-basis section above. Do not merge them.
- `unbalanced_document` is decided on `debit_amount − credit_amount`, never
  on `local_amount`.
- `is_fraud` / `is_anomaly` are never grounds to delete a row. They only
  label a mismatch, if one exists.
- If `unknown` mismatches exceed 20% of the period's total mismatch count,
  the period report cannot be signed.
- An intended fix (the excluded-by-design cases above) must point to a cause
  already in this list. No label invented in the query.

## map_account uniqueness (map_fanout)

`map_account.source_account` must be unique. A duplicate `source_account`
joined against `stg_gl` fans out rows and inflates totals with no error.

- Duplicate `source_account` is a blocking error named `map_fanout`.
- Checked before every period load, not only at mapping-review time.
- On detection, nothing in scope of that mapping row loads into
  `fact_gl_line` until the duplicate is resolved.
- Many sources mapping to one target is allowed. That is the point of
  rolling 505 accounts into ~27 classes. One source mapping to many targets
  is the fan-out case this guards against.

## unmapped_account / target chart of accounts

No real target chart of accounts exists yet. First pass derives one from the
source hierarchy at `account_class` grain (~27 rows, rolled up from 505
`gl_account` values via `account_sub_class → account_class`).

`map_account.csv` columns: `source_account, target_account, status,
source_usage, account_role, dq_flag, pair_id, notes`. A human approves this
file. No target code is invented. `unmapped_account` means a `gl_account`
not present in `map_account`, or present with `status != mapped`.

**`status`** answers one question only: does this source account have a
place in the target chart of accounts, and where. It is one of `mapped`,
`unmapped`, `deprecated`, `catch_all` (see ADR-0005 for `catch_all`).
It says nothing about whether the account is still receiving postings in
the source system today. That is a separate question, answered by
`source_usage`.

- `mapped`: has a `target_account`.
- `unmapped`: no `target_account` decided yet. Not a claim the account is
  inactive or safe to drop.
- `deprecated`: this source code will not be carried into the target CoA.
  **If `source_usage=live`, a `deprecated` row must still carry a
  `target_account`** (the account's own source code, not an invented
  number, not the `account_class`) so live postings have somewhere to land.
  A `deprecated` row with no `target_account` is only valid when
  `source_usage != live`.
- `catch_all`: a migration parking code, not a real account. See ADR-0005.

**`target_account`** is either the source's own `account_class` (the
default, for an ordinary account rolling up into the ~27-class target CoA),
or the account's own `source_account` code, when `account_role` is
`clearing`, `clearing_pair`, or the row's `status` is `catch_all`. These
represent operational codes that keep their own identity rather than
rolling into a class. Never a class code (`account_class`) for a
`catch_all` row: two catch-all codes can carry different
`financial_statement_category` values in the same scope and folding them
into one class target would misclassify one of them.

**`source_usage`** is one of `live`, `retired`. Computed over the full
source data, not the current migration scope: `live` if the account has any
`debit_amount` or `credit_amount` activity anywhere (any company, any
period, in or out of scope), or appears in a period after the current
scope's latest period, or in a company outside the current scope. `retired`
otherwise. Never computed from `local_amount` alone. See the
`local_amount_zero_but_dr_cr_nonzero` dq_flag below for why. A third value,
`dormant`, is deliberately not defined yet: no criteria for it exist, and
adding it without one would just be a guess wearing a label.

**`account_role`** is optional metadata on what the account does:
`clearing` (a single clearing/suspense account, one coherent job) or
`clearing_pair` (one side of a debit-only/credit-only pair that only makes
sense read together, see `pair_id`). Blank for an ordinary account.

**`dq_flag`** is optional metadata: a named data-quality concern to keep
visible, not silently drop. `local_amount_zero_but_dr_cr_nonzero` marks a
`gl_account` where every row's `local_amount` is 0 while `debit_amount` /
`credit_amount` are materially nonzero. A `local_amount`-only view of
this account is misleading. Filed against issue #5.

**`pair_id`** links the two sides of a `clearing_pair`: same value on both
rows (e.g. `115020_205020`). A `clearing_pair` row present without its
other half, or with the two halves on different `status` values, is a
validation error, not a valid state.

**`notes`** is free text. Required when a `deprecated` row has no
`target_account`, to say why.

## "Close a period" / deliverable / tolerance

This project has no live accounting system, so "close" is not a system
state. It is a signed-off artifact, **`reports/period_2024-01.md`**, one
file per period, containing at minimum:

1. `stg_gl` total against `fact_gl_line` total, per account.
2. Count of documents not matching, split by bucket (`missing_in_fact`,
   `missing_in_stg`, `amount_changed`, `intentionally_excluded`).
3. A cause table. See "Mismatch classification" above.

**Tolerance:** checked to 0.01. A gap at or under 0.01 is auto-labeled
`rounding`. A gap over 0.01 must carry a real cause, never `unknown`.

A period is closed in this project when someone accepts that report, not
when a table has rows.

## Reversals

No `is_cancelled` column. `predecessor_line_id` is populated for only 13 of
40,386 rows in scope, too sparse to be a rule. The real signal is a textual
convention:

- `reference` starts with `REV-<uuid>`
- `header_text` reads `Reversal of <document_id>`

Detect reversal documents from this convention, link each to its original,
and report them as their own bucket ("reversal pairs"): count, net amount
(should be about 0), and the linked document ids. Never delete either side
of a reversal pair.

## cancelled / reversal (superseded rule)

Superseded by the section above, kept for cross-reference: do not infer
cancellation from document numbers, and do not invent a status column that
does not exist.

## publishable

A document or line is publishable only when all of these hold:

- passes the blocking DQ checks (`unbalanced_document`, `duplicate_source`,
  `map_fanout`)
- doc_type has `include_in_close = yes`
- not `is_post_close`
- account is `mapped` in `map_account`, and that mapping row is not part of
  a `map_fanout` violation
- loaded through the idempotent (replace-whole-period) path
