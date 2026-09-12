# Mission 19: one recon_mismatch row per source line, document-level cause wins

- **Signal:** issue #19, no blocker.
- **Confidence:** high on the fix shape (your ruling locked the exact
  priority order and the grain to key on). Exploration below confirms it
  changes zero real numbers today.
- **Type:** bug fix - `reconcile_mismatch.py`'s dq_violations join
  multiplies a row instead of picking one cause when more than one
  blocking check applies to the same line.
- **Decision:** act, on the exact rule you gave. Document-level blocking
  outranks line-level blocking, which outranks non-blocking. Every
  finding stays in `dq_violations`; only `recon_mismatch`'s one-row-per-
  line output changes.

## Rules that apply

> "เกตระดับเอกสารชนะเกตระดับบรรทัด... 1. dq_violations เก็บครบทุกใบ...
> ห้ามลบเกตหนึ่งเพราะอีกเกตชนะ ตารางนี้คือสมุดหลักฐาน 2. recon_mismatch
> มีได้แถวเดียวต่อ 1 บรรทัดต้นทาง กุญแจคือ (company_code, document_id,
> line_number, fiscal_year, fiscal_period) ห้ามแถวเดียวกันมีสองสาเหตุ
> 3. ลำดับเลือก cause เมื่อชนกัน: เกตบล็อกระดับเอกสาร (unbalanced_document)
> มาก่อน เพราะกฎ publish คือทั้งฉบับห้ามเข้า fact / เกตบล็อกระดับบรรทัด
> เช่น duplicate_source, null_key_column, map_fanout / เกตไม่บล็อก เช่น
> unmapped_account ใช้เป็นสาเหตุได้เฉพาะเมื่อไม่มีเกตบล็อก 4. บัญชีที่
> map_fanout จับแล้ว ห้ามเข้า unmapped_account"
> (your ruling on this ticket - document-level blocking wins, every
> dq_violations finding stays logged, one mismatch row per source line)

> "อย่าเลือกสาเหตุด้วย MIN(check_name) แล้วจบ / อย่ายุบ dq_violations
> เหลือใบเดียว / อย่าแก้เฉพาะ fixture แล้วไม่ล็อกกฎ"
> (explicit non-goals in the same ruling)

A second question came up mid-build: a duplicated grain
(`duplicate_source`) means more than one physical `stg_gl` row shares the
same 5-column key. Does the one-row rule count by grain or by physical
row? Your answer:

> "เหลือ 1 แถวต่อ grain อย่านับตามแถวกายภาพใน stg_gl... ถ้าแถวซ้ำ 2 แถวมี
> ยอดเดียวกัน แล้วนับ 2 แถว mismatch ยอดจะพอง จำนวนแถวซ้ำเป็นเรื่องเกต
> ไม่ใช่เรื่องกุญแจปิดงวด เก็บความซ้ำไว้ที่ dq_violations
> check_name=duplicate_source... ห้ามให้ SUM(gap) คูณตามจำนวนแถวซ้ำ"
> (one grain = one recon_mismatch row; the physical duplicate count is
> dq_violations' job, not recon_mismatch's; never let SUM(gap) multiply
> by duplicate row count)

## Exploration

Traced during the `/scrutinize` pass that opened this issue: run the real
CI pipeline against `tests/fixtures/journal_entries_ci.parquet`, then read
`recon_mismatch` directly for `CI-DOC-DUP-001`, which has 2 physical
`stg_gl` rows for `line_number=1` and both an `unbalanced_document`
(document grain) and a `duplicate_source` (line grain) blocking violation:

```
CI-DOC-DUP-001, line 1: 4 recon_mismatch rows (2 unbalanced_document, 2 duplicate_source)
CI-DOC-DUP-001, line 2: 1 recon_mismatch row (unbalanced_document)
```

2 physical source rows should produce at most 2 recon_mismatch rows for
line 1, not 4. Cause: the join's `ON` clause (`v.line_number IS NULL OR
v.line_number = c.line_number`) matches every blocking violation that
applies to a line, document-grain and line-grain alike, and DuckDB
produces one output row per match.

**Real data (company 1000, 2024, P01-P03), checked directly against
`warehouse.duckdb`:**

```
dq_violations, real scope: unbalanced_document(1), catch_all_account(252),
  local_amount_imbalance(93), unmapped_account(41).
  map_fanout=0, null_key_column=0, duplicate_source=0, unmapped_doc_type=0.
recon_mismatch cause, real scope: opening_balance(17), post_close(363),
  unbalanced_document(2). Nothing else appears.
```

No real document has two blocking violations today, so the fix is a no-op
against every signed `reports/period_2024-0{1,2,3}.md`. Matches
`src/checks.py`'s existing pinned anchor
(`mismatch_known_counts`: 17 opening_balance, 200 post_close [P01 only],
2 unbalanced_document) - that anchor must not move.

**A second fan-out, found while verifying the first fix, not before it:**
the priority QUALIFY partitions by grain alone, so when a grain has more
than one physical `stg_gl` row (`duplicate_source`'s own definition), all
of that grain's candidates collapse into 1 recon_mismatch row regardless
of physical row count, not 1-per-physical-row. First build assumed the
latter and got it wrong: `CI-DOC-DUP-001` line 1 produced 1 row, not the
2 the first draft of `tests/ci_checks.py` expected. Traced directly:

```
2 physical rows -> v-join produces 4 candidates (2 rows x 2 matching checks)
-> QUALIFY partitioned by grain alone keeps 1 total, not 2
```

Put to you rather than guessed: your answer was 1 row per grain, not per
physical row, so the shipped behavior needed no code change, only the
fixture check's wrong expectation fixed.

**A second, smaller gap found while designing the fix, not introduced by
it:** `src/checks.py`'s `VALID_CAUSES` and `docs/definitions.md`'s cause
list are both missing `map_fanout` and `null_key_column` as valid
`recon_mismatch.cause` values, even though both are real blocking
`check_name`s that the existing (buggy) join already could have written
into `cause` before this fix, the same way `duplicate_source` and
`unmapped_doc_type` already can. Latent, like the row-multiplying bug
itself - zero real occurrences today - but your rule explicitly names
both as tier-2 causes, so this fix needs them added to the fixed list
first, per this repo's own "no cause invented in SQL" rule.

`catch_all_account` (also non-blocking, tier 3) is deliberately **not**
added to the fixed list. Tracing `classified`'s CASE expression: the
`COALESCE(c.cause, v.check_name)` fallback to `v.check_name` only ever
fires for the `missing_in_fact` bucket, and a line can only be
`missing_in_fact` because a blocking check excluded it from
`fact_gl_line` in the first place (`load_fact.py`'s insert has no other
exclusion path). So tier 3 (non-blocking as cause) is unreachable in
today's architecture - implemented anyway, because your rule states it
as a general principle, not a fixture patch, but nothing today can
exercise `catch_all_account` or `local_amount_imbalance` through this
path, so neither goes in the fixed list until something real can.

## Desired outcomes

- `reconcile_mismatch.py`: the dq_violations join picks exactly one
  `check_name` per `(company_code, document_id, line_number, fiscal_year,
  fiscal_period)`, by two-level priority: (1) blocking + document-grain
  (`line_number IS NULL`) beats (2) blocking + line-grain beats (3)
  non-blocking. Ties inside a tier break by the check's position in
  `quality_gate.py`'s own `CHECK_NAMES` tuple - an order that already
  exists and already happens to encode the same 3 tiers, reused rather
  than invented fresh.
- `dq_violations` itself is untouched. Every check still logs every
  finding it always did.
- `quality_gate.py`'s `unmapped_account` query excludes any `gl_account`
  already caught by `map_fanout`, reusing the account list `map_fanout`
  already computes, so a bad mapping file produces one blocking finding
  instead of one blocking plus a doubled non-blocking one.
- `docs/definitions.md` states the priority rule and adds `map_fanout` /
  `null_key_column` to the valid cause list.
- New ADR recording the "document-grain cause wins" decision and why.

## Deterministic checks

- [x] `CI-DOC-DUP-001` line 1: `recon_mismatch` has exactly 1 row (one
      per grain, not one per physical `stg_gl` row), cause
      `unbalanced_document`. Line 2: still 1 row, cause
      `unbalanced_document` (unchanged, only ever had one candidate).
- [x] `dq_violations` for `CI-DOC-DUP-001` still carries both
      `unbalanced_document` and `duplicate_source` - nothing deleted.
- [x] Real dataset: `mismatch_known_counts`'s pinned P01 anchor (17/200/2)
      unchanged, re-verified by rerunning `reconcile_mismatch.py` against
      the real warehouse, not assumed from the code diff.
- [x] `src/checks.py` green after the change, count included, since 2
      new checks are added in this ticket (map_fanout/unmapped_account
      overlap, and the multi-cause priority itself as a synthetic proof
      matching the fixture finding).
- [x] `tests/ci_checks.py` gets a check asserting the fixed
      `CI-DOC-DUP-001` recon_mismatch row count, so this can't regress
      silently again.
- [x] A duplicated `map_account.source_account` (synthetic, never real
      map_account.csv) no longer produces a doubled `unmapped_account`
      finding for the same `gl_account`.

## Non-goals

- Not adding a column (e.g. `source_row_count`) to `recon_mismatch` to
  surface how many physical `stg_gl` rows a deduplicated grain
  represented. You raised it as an option, not a requirement, and it's a
  schema change touching every existing row and every report query that
  reads this table - real scope for a ticket of its own if you want it,
  not a rider on this one. The duplicate count stays visible in
  `dq_violations` (`check_name = duplicate_source`) either way.
- Not deciding which physical row's `gap` survives when a duplicated
  grain's copies carry different amounts (today's fixture happens to
  have identical amounts on both copies, so this never shows). Picking
  one would be the same "which copy is real" call
  `docs/definitions.md`'s existing duplicate-grain section already
  refuses to make in SQL - a human decides, same as there.
- Not touching the `p` (`recon_reversal_pairs`) enrichment join in the
  same query. Same latent multi-match shape (a `document_id` could in
  principle appear twice in the reversal-pairs union), but zero real
  `document_id`s hit it today, and it wasn't what the fixture caught.
  Noted, not acted on - same treatment mission 18's retro gave
  `reconcile_reversals.py`'s hardcoded scope constants.
- Not adding `catch_all_account` or `local_amount_imbalance` to
  `recon_mismatch`'s valid cause list. Traced as currently unreachable
  through this join (see Exploration) - adding them now would be a
  guess about a path nothing can take yet.
- Not touching `build_mapping.py`, the majority-vote logic, or the
  115/205 clearing-pair family.
- Not starting Airflow. A DAG built on the current join would carry the
  same double-count forward - stays parked until this closes.

## Human approvals

**Before build:** none needed beyond this ticket's own ruling - the
priority order, the grain, and the tie-break precedence were all locked
before any SQL changed.

**Before the output is used:** confirm the real-data no-op claim holds
and the fixture now produces the expected single row per line, then
comment "approved" on #19.

## Retro

The fix itself was small: a `QUALIFY ROW_NUMBER()` collapsing the join's
candidate rows down to one per grain, ranked by a tier CASE plus a reused
ordering (`quality_gate.CHECK_NAMES`) instead of a second, hand-invented
list. The harder part was a question the fix's own shape raised that
nobody had asked yet: does "one row per grain" also mean collapsing a
grain's own physical duplicates, or just its violation matches? The first
draft of `tests/ci_checks.py` assumed the answer without noticing it had
assumed anything, then failed against the code that actually matched your
literal rule #2 wording. Worth noticing: the code was right and the test
was wrong, the reverse of the usual order. Put the real fork to you rather
than picking - one grain, one row, physical duplicate count stays in
dq_violations - and only the test's expectation needed fixing, not the
SQL.

Real data stayed a proven no-op both times: zero documents with two
blocking checks at once, zero duplicated grains, checked directly against
`warehouse.duckdb` before writing a line of SQL, not assumed from the
fixture. `mismatch_known_counts`' P01 anchor (17/200/2) never moved,
`recon_mismatch`'s real row count stayed at exactly 382 before and after
rerunning the fix against the real warehouse.

The `VALID_CAUSES` gap (`map_fanout` and `null_key_column` never added as
legal `recon_mismatch` causes, even though they're real blocking check
names that always could have landed there) wasn't something this ticket
went looking for - it surfaced because the priority rule needed to name
every tier-2 check, and two of them weren't in the fixed list yet. Added
both, left `catch_all_account` out, since tracing `classified`'s own CASE
expression shows that path is unreachable while `load_fact.py`'s only
exclusion mechanism is a blocking violation. Not adding an allowance for a
path nothing can take yet, even though the shape of the rule would
technically support it.

`unmapped_account`'s map_fanout exclusion turned out to fix two things
with one line: the semantic overlap you asked about (don't log a mapping
problem under two check names) and the fan-out risk from the earlier
`/scrutinize` pass (a duplicated `source_account` fanning out the
`unmapped_account` join itself), for free, since excluding the account
from the query entirely removes both its copies from the join before
either could log anything.
