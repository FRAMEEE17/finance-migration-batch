# Mission 05: Quality gate + dq_violations

- **Signal:** issue #5, blocked by #4 (closed)
- **Confidence:** high. Written AC, grounded in `docs/business-rules.md`
  and `docs/definitions.md`.
- **Type:** request. Mechanical relative to #3 (no business judgement on
  what an account means), but it changes existing, working code in
  `src/load_fact.py`, not just adds new code.
- **Decision:** act. Pull the blocking checks into one shared gate module,
  add the three checks ticket 4 didn't need, and replace
  `fact_gl_line_rejected` with the real `dq_violations` table.

## Rules that apply

> "Put the quality gate in front of `fact_gl_line`: run the audits, and
> only publish what passes. Rejected rows go to `dq_violations` so they
> stay visible, nothing is silently dropped." (issue #5)

> "**Unbalanced document** (`debit_amount − credit_amount != 0`): load to
> staging, never publish, must be caught by a check named
> `unbalanced_document`." (docs/business-rules.md)

> "**Duplicate grain:** blocking violation `duplicate_source`, never
> auto-dedup." (docs/business-rules.md)

> "`source_account` must be unique; duplicates are a blocking `map_fanout`
> error, checked every load." (docs/business-rules.md)

> "`local_amount` not netting to zero on an otherwise-balanced document is
> its own finding (`local_amount_imbalance`), not a publish blocker."
> (docs/business-rules.md)

> "**Flagged rows (`is_fraud`, `is_anomaly`, `is_post_close`):** these are
> reconciliation content, never a filter." (docs/business-rules.md, ADR-0003)

> mission 04's retro: "`fact_gl_line_rejected` is deliberately thin...
> because #5 owns the real `dq_violations` design."

## Exploration

`notebooks/05-quality-gate.ipynb`. Checked how many of the 4 blocking
checks and 2 non-blocking findings have a real case in the P01 scope
before designing the gate:

| check | blocking | real cases |
|---|---|---|
| `unbalanced_document` | yes | 1 document (already excluded by #4) |
| `duplicate_source` | yes | 0 |
| `map_fanout` | yes | 0 |
| null key column | yes | 0 |
| `local_amount_imbalance` | no | 23 documents |
| `unmapped_account` | no | 85 lines (`catch_all` + `unmapped` map_status) |

Three of the four blocking checks have nothing real to catch this period
and need a synthetic-row proof, same pattern as #4's `unmapped_doc_type`
check. `unmapped_account` counts both `catch_all` and `unmapped` rows,
per `docs/definitions.md`'s "`status != mapped`" wording, not just literal
`status=unmapped`.

## Desired outcomes

- `src/quality_gate.py`: one module, one function that runs all 4 blocking
  checks against a scope and returns which documents/rows pass, plus the
  2 non-blocking findings as records to log. `unbalanced_document`'s logic
  moves here from `src/load_fact.py`, not duplicated.
- `dq_violations` table in `warehouse.duckdb`: `check_name, blocking,
  company_code, document_id, line_number, fiscal_year, fiscal_period,
  detail, checked_at`. One row per finding, blocking and non-blocking
  alike, replacing `fact_gl_line_rejected`.
- `src/load_fact.py` calls the gate instead of running its own inline
  `unbalanced_document` SQL. Behavior for that one check must not change:
  same document still excluded, same reason.
- Per-check counts printed after every run of `src/load_fact.py`.

## Deterministic checks

- [ ] The 1 known unbalanced document is in `dq_violations`
      (`check_name='unbalanced_document', blocking=true`) and absent from
      `fact_gl_line`, exactly as it was under #4's inline check.
- [ ] A synthetic duplicate-grain row is rejected and logged
      (`check_name='duplicate_source'`).
- [ ] A synthetic `map_fanout` case (two `map_account.csv` rows sharing a
      `source_account`) is rejected and logged. Never touches the real
      `map_account.csv`.
- [ ] A synthetic null-key-column row is rejected and logged.
- [ ] All 23 known `local_amount_imbalance` documents appear in
      `dq_violations` with `blocking=false`, and are still present in
      `fact_gl_line` (non-blocking never excludes).
- [ ] All 85 known `unmapped_account` lines (`catch_all` + `unmapped`
      `map_status`) appear in `dq_violations` with `blocking=false`, and
      are still present in `fact_gl_line`.
- [ ] `is_fraud`/`is_anomaly` rows are not filtered anywhere in the gate:
      a fraud/anomaly-flagged row that would otherwise pass still passes,
      one that would otherwise be rejected still gets rejected (flags
      never enter the predicate).
- [ ] Re-running `src/load_fact.py` twice gives identical `dq_violations`
      row counts per check, same idempotency bar as #4's `fact_gl_line`.

## Non-deterministic checks

| Check | Who | How an agent verifies |
|---|---|---|
| "null in a key column" is the right column set (grain + `gl_account`) | you | agent lists the exact columns the check covers and asks you to confirm nothing's missing (e.g. `debit_amount`/`credit_amount` themselves) |

## Non-goals

- Not parameterizing `src/load_fact.py`/`src/quality_gate.py` for a
  different company or period. Still hardcoded to company 1000, FY2024
  P01, same as #4. Generalizing for P02/P03 is #10's job.
- Not building `recon_period_summary`/`recon_mismatch`. #6/#8.
- Not deciding what happens to `catch_all`/`unmapped` rows at
  reconciliation time, only flagging them as a finding now. The
  `unmapped_account` cause classification itself is #6/#8's job.
- Not adding new blocking checks beyond the 4 named in issue #5. A
  `local_amount_imbalance` gap over some threshold, for instance, is not
  becoming a 5th blocking check here without a separate ruling.

## Human approvals

**Before build:**

- `dq_violations` schema as listed above, one table for blocking and
  non-blocking findings together, not two tables
- `fact_gl_line_rejected` (ticket 4's placeholder) is dropped once
  `dq_violations` replaces it, not kept alongside it
- `unmapped_account` counts any `map_status != 'mapped'`, including
  `catch_all`, not just literal `status='unmapped'`
- key columns for the null check: `company_code, document_id,
  line_number, fiscal_year, fiscal_period, gl_account`
- synthetic-row tests for the three checks with no real case this period,
  never touching real `stg_gl` or `map_account.csv` data

**Before the output is used (#6+):**

- you spot-check the 23 `local_amount_imbalance` documents and the 85
  `unmapped_account` lines in `dq_violations`, confirm the per-check
  counts printed after a run look right, comment "approved" on #5

## Retro

Filled after the mission closes.
