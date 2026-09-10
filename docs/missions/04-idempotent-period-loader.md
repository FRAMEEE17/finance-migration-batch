# Mission 04: Idempotent period loader (2024-01)

- **Signal:** issue #4, part of the 12-ticket plan
- **Confidence:** high. Written AC, grounded in `docs/business-rules.md` and
  `docs/definitions.md`, no open GitHub blocker.
- **Type:** request. Mechanical relative to #3 (no business judgement on
  what an account means), but the transaction/idempotency correctness is
  real engineering risk if gotten wrong quietly.
- **Decision:** act. Build `fact_gl_line` for company 1000, period
  (2024, 01) only. Replace-whole-period semantics, one transaction, proven
  idempotent by two consecutive runs.

## Rules that apply

> "**Period load:** replacing a period replaces the **whole** period, never
> append. Re-running with unchanged mapping must yield the same totals and
> row counts." (docs/business-rules.md)

> "**Unbalanced document** (`debit_amount − credit_amount != 0`): load to
> staging, never publish, must be caught by a check named
> `unbalanced_document`." (docs/business-rules.md)

> "**Doc types counted in period close:** `SA, DR, KR, DZ, KZ, AA, WE, WL,
> HR, IC`... `OPENING_BALANCE`: brought-forward balance. Separate flag,
> never mixed into in-period totals... `CL`: closing entry. Not in
> in-period totals... **Unknown doc type**: do not count it in the close,
> set status `unmapped_doc_type`, do not guess revenue vs expense."
> (docs/business-rules.md)

> "**Flagged rows (`is_fraud`, `is_anomaly`, `is_post_close`):** these are
> reconciliation content, never a filter." (docs/business-rules.md, and
> ADR-0003)

> "**Duplicate grain:** blocking violation `duplicate_source`, never
> auto-dedup." (docs/business-rules.md)

> "Money. Two different checks, not interchangeable: Balance validation...
> uses `debit_amount − credit_amount`. Close totals... use `local_amount`.
> Never sum `transaction_amount` to close a period." (docs/business-rules.md)

## Exploration

`notebooks/04-idempotent-period-loader.ipynb`. Checked the actual scope
(company 1000, FY2024 P01) before locking the checks below:

- 13,142 rows, 3,518 distinct documents.
- `document_type` distribution: `DR 4248/1183, KR 4168/1023, SA 2903/822,
  HR 1348/328, AA 419/142, IC 31/15, OPENING_BALANCE 17/1, WE 4/2, WL 4/2`.
  Every type present is in the counted catalog except `OPENING_BALANCE`.
  No `unmapped_doc_type` case exists in this period.
- Exactly 1 unbalanced document (`gap = 90.0`, not fraud/anomaly-flagged).
  A real, small, hand-checkable case for the `unbalanced_document` rule.
- 0 duplicate-grain groups this period.
- `is_post_close=200, is_fraud=326, is_anomaly=516` rows present. All three
  must still load.

What this changed: confirmed `OPENING_BALANCE` needs to stay in the table
(real volume, not a zero case) and confirmed the unbalanced-document rule
has something real to prove itself against. Flagged as a gap: this period
alone can't prove `unmapped_doc_type` fires correctly, since nothing here
triggers it.

## Desired outcomes

- `fact_gl_line` table in `warehouse.duckdb`: company 1000, FY2024 P01
  only. Same grain as `stg_gl` (`company_code, document_id, line_number,
  fiscal_year, fiscal_period`), plus `target_account` and `map_status`
  joined from `map_account.csv`, plus `loaded_at`.
- `src/load_fact.py`: one script, one transaction per run. Delete the
  period's existing rows (if any), re-insert, commit. A failure partway
  through must leave whatever was there before the run untouched (no
  partial period).
- Console log per run: row count, distinct document count,
  `SUM(local_amount)`, timestamp. The same three numbers the idempotency
  check compares.

## Deterministic checks

- [x] `fact_gl_line` contains only `company_code=1000, fiscal_year=2024,
      fiscal_period=1` rows. No other scope leaks in.
- [x] Running the loader twice back to back gives identical row count,
      distinct `document_id` count, and `SUM(local_amount)` (to the cent).
- [x] The 1 known unbalanced document is absent from `fact_gl_line` and
      still present in `stg_gl`.
- [x] Row count in `fact_gl_line` for this period ≤ row count in `stg_gl`
      for the same scope (nothing invented, only ever a subset).
- [x] Every `fact_gl_line` row's `gl_account` appears in `map_account.csv`
      (`target_account`/`map_status` came from the approved mapping, not
      guessed inline).
- [x] `is_fraud`, `is_anomaly`, `is_post_close` values on loaded rows match
      `stg_gl` exactly (untouched, not re-derived).
- [x] Killing the load mid-transaction (simulated) leaves the prior
      `fact_gl_line` state for this period exactly as it was before the run.

## Non-deterministic checks

| Check | Who | How an agent verifies |
|---|---|---|
| the `OPENING_BALANCE` row stays in `fact_gl_line` with a flag rather than being excluded from the table entirely | you | agent shows the 17 rows are present post-load and confirms they carry a value that lets #9's report exclude them from the close total without excluding them from the table |
| the unbalanced-document exclusion is correctly scoped (the whole document drops, not just the imbalanced line) | you | agent confirms all lines of that one document_id are absent from fact_gl_line, not just the line causing the gap |

## Non-goals

- No reconciliation (`recon_period_summary`/`recon_mismatch`). #6/#8.
- No `dq_violations` table or formal blocking-check gate with per-check
  counts. That's #5's scope; #4 only implements the one exclusion rule
  (`unbalanced_document`) that's fundamental to what "publish" means, not
  the full audit trail around it.
- No backfill to P02/P03 or other companies. #10.
- No reversal-pair detection. #7.
- Not proving `unmapped_doc_type` fires correctly. No case exists in this
  period to prove it against (see Exploration). The column/logic still
  needs to exist; just can't be checked here.

## Human approvals

**Before build:**

- `fact_gl_line` keeps `OPENING_BALANCE` rows in the table (flagged, not
  excluded); `CL` isn't present this period so the same rule applies by
  extension, not by evidence
- the 1 unbalanced document (and all its lines) is excluded from
  `fact_gl_line` entirely, not loaded-then-flagged, matching the "never
  publish" wording, unlike `OPENING_BALANCE`'s "separate flag" wording
- unmapped-status accounts still load into `fact_gl_line` with
  `target_account` blank (the `unmapped_account` mismatch cause is
  resolved at reconciliation time, #6/#8, not by excluding the row now)
- one transaction: `BEGIN`, delete-this-period, insert-this-period,
  `COMMIT`; any exception rolls back and leaves the prior state intact
- `#5`'s full quality gate (dq_violations, blocking-check counts) is
  explicitly out of scope here, see Non-goals

**Before the output is used (#5+):**

- you spot-check the unbalanced document and the OPENING_BALANCE rows in
  the built `fact_gl_line`, confirm the two idempotency runs actually
  match, comment "approved" on #4

## Retro

Built with four additions on top of the original before-build approval,
all requested before code: `is_opening_balance`/`is_closing_entry` as real
columns (not a side table), a `fact_gl_line_rejected` table so an excluded
document leaves a trace instead of vanishing, `unbalanced_document`
checked on the whole document's debit/credit (never `local_amount` alone,
the same lesson mission 01 already paid for), and a synthetic-row test
proving `unmapped_doc_type` rejects an unrecognized type even though no
real case exists in P01 to prove it against.

The one durable rule this mission adds: **a loader's exclusion rules need
a real place for what they excluded to land, even before the ticket that
owns the formal version exists.** `fact_gl_line_rejected` is deliberately
thin (grain + reason + timestamp, no severity or detail columns) because
#5 owns the real `dq_violations` design; this mission's job was only to
not let two live document rows disappear without a trace while #5 doesn't
exist yet.

Verified: three consecutive runs of `src/load_fact.py` produced identical
`13,140 rows, 3,517 documents, SUM(local_amount)=97,144,587.13` every
time. 21/21 regression checks green.
