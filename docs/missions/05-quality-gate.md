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

> "`unmapped_account` means a `gl_account` not present in
> `map_account.csv`, present with `status='unmapped'`, or present with
> `status='deprecated'` and no `target_account`. It does not mean
> `status='catch_all'`. A catch-all row already has a resolved
> classification (ADR-0005)... A `catch_all` row gets its own non-blocking
> finding, `catch_all_account`." (docs/definitions.md, revised this mission)

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
| `unmapped_account` | no | 15 lines (literal `status='unmapped'` only) |
| `catch_all_account` | no | 70 lines (`status='catch_all'`, split out) |

Three of the four blocking checks have nothing real to catch this period
and need a synthetic-row proof, same pattern as #4's `unmapped_doc_type`
check.

`unmapped_account` and `catch_all` got checked together in the first pass
of this exploration (85 lines combined) and then split apart: a
`catch_all` row is a resolved classification from ADR-0005, not an
unresolved mapping gap, so counting it as `unmapped_account` would make a
decision look like an open question. Fixed in `docs/definitions.md` and
`CONTEXT.md` before this mission's build started, not left as a build-time
judgement call.

Also checked and explicitly not built this round: whether a
`clearing_pair`'s other side is missing from `fact_gl_line`. `115020` has
zero rows in P01 (real: its activity starts P02), which would fire a
naive version of this check as a false positive. It isn't a defect, just
a normal single-period timing gap, so this check needs cross-period
visibility #5 doesn't have. Left for whichever ticket builds that
visibility, not invented here to look complete.

## Desired outcomes

- `src/quality_gate.py`: one module, one function that runs all 4 blocking
  checks against a scope and returns which documents/rows pass, plus the
  2 non-blocking findings as records to log. `unbalanced_document`'s logic
  moves here from `src/load_fact.py`, not duplicated.
- `dq_violations` table in `warehouse.duckdb`: `check_name, blocking,
  company_code, document_id, line_number, fiscal_year, fiscal_period,
  detail, checked_at`. `check_name` is a closed set in code (not a free
  string): `unbalanced_document, duplicate_source, map_fanout,
  null_key_column, local_amount_imbalance, unmapped_account,
  catch_all_account`. `line_number` is nullable, for a check that
  operates at document grain (`unbalanced_document`,
  `local_amount_imbalance`); every other check logs one row per line, the
  grain it actually checked, never collapsed into one summary row per
  account. Replaces `fact_gl_line_rejected`.
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
- [ ] All 15 known `unmapped_account` lines (literal `status='unmapped'`,
      the clearing-pair accounts) appear in `dq_violations` with
      `blocking=false`, still present in `fact_gl_line`.
- [ ] All 70 known `catch_all_account` lines (`status='catch_all'`) appear
      in `dq_violations` with `blocking=false`, still present in
      `fact_gl_line`, and never counted toward `unmapped_account`.
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
- Not checking whether a `clearing_pair`'s other side is missing from
  `fact_gl_line`. A real single-period case exists (`115020`, zero rows
  in P01) but it's a timing fact, not a defect; a correct version of this
  check needs visibility past one period, which #5 doesn't have.

## Human approvals

**Before build:**

- `dq_violations` schema as listed above, one table for blocking and
  non-blocking findings together, not two tables
- `fact_gl_line_rejected` (ticket 4's placeholder) is dropped once
  `dq_violations` replaces it, not kept alongside it
- `unmapped_account` means literal `status='unmapped'` or
  `status='deprecated'` with no `target_account`, never `catch_all`.
  `catch_all` gets its own non-blocking finding, `catch_all_account`.
  Fixed in `docs/definitions.md`/`CONTEXT.md` ahead of the build.
- key columns for the null check: `company_code, document_id,
  line_number, fiscal_year, fiscal_period, gl_account`. `target_account`
  is explicitly not a key column here: a blank target is a mapping gap,
  not a missing source key.
- synthetic-row tests for the three checks with no real case this period,
  never touching real `stg_gl` or `map_account.csv` data
- no check for a `clearing_pair`'s missing other side this round (see
  Non-goals)

**Before the output is used (#6+):**

- you spot-check the 23 `local_amount_imbalance` documents, the 15
  `unmapped_account` lines, and the 70 `catch_all_account` lines in
  `dq_violations`, confirm the per-check counts printed after a run look
  right, comment "approved" on #5

## Retro

Filled after the mission closes.
