# Mission 08: Document-level reconciliation with bucket + cause

- **Signal:** issue #8, blocked by nothing explicit, but reads
  `fact_gl_line`, `dq_violations` (#5) and `recon_reversal_pairs` (#7),
  both closed.
- **Confidence:** medium. The mechanical join is straightforward; two of
  the five `intentionally_excluded` causes have no real trigger in P01
  to derive their logic from, which is a real design gap, not just a
  quiet corner.
- **Type:** request with an embedded design gap. The issue's literal
  instruction ("FULL OUTER JOIN stg_gl to fact_gl_line") turns out to be
  under-specified: taken completely literally, it can only ever produce
  one of the four required buckets.
- **Decision:** act, bounded. Build what the exploration grounds
  (`missing_in_fact`, `intentionally_excluded` for `opening_balance` and
  `post_close`), escalate the two ungrounded causes
  (`closing_entry`, `reversal_pair`) for a ruling before writing their
  logic, don't guess at a trigger condition neither the issue text nor
  the data supplies.

## Rules that apply

> "Document-level reconciliation into `recon_mismatch`. FULL OUTER JOIN
> `stg_gl` to `fact_gl_line` on the grain. Classify every difference with
> one bucket (the symptom) and one cause (the reason)... `reversal_pair`
> causes come from the #7 pair table." (issue #8)

> "**Bucket**: Which symptom a mismatch shows (`missing_in_fact`,
> `missing_in_stg`, `amount_changed`, `intentionally_excluded`)."
> (CONTEXT.md)

> "`intentionally_excluded` pairs only with: `opening_balance`,
> `closing_entry`, `post_close`, `out_of_scope_period`, `reversal_pair`."
> (docs/definitions.md)

> "**Period-boundary document**: An `OPENING_BALANCE` (brought-forward)
> or `CL` (closing) document. Excluded from in-period close totals by
> design. This is an intended fix, not a mismatch to investigate."
> (CONTEXT.md)

> "`unknown` > 20% of a period's mismatches blocks sign-off."
> (docs/business-rules.md)

## Exploration

`notebooks/08-document-level-reconciliation.ipynb`. Scope: company 1000,
FY2024 P01 (the only period `fact_gl_line` covers).

**A literal FULL OUTER JOIN against the full `fact_gl_line` table only
ever produces `missing_in_fact`.** `opening_balance`/`post_close` rows
are loaded and flagged, never excluded from the table (mission 04's
decision), so a row-for-row join finds them perfectly matched, not
mismatched. Under this reading, 3 of the 4 required buckets
(`missing_in_stg`, `amount_changed`, `intentionally_excluded`) would be
permanently unreachable, not just empty this period.

**Comparing `stg_gl` against `fact_gl_line`'s close-eligible subset**
(`WHERE NOT is_opening_balance AND NOT is_closing_entry AND NOT
is_post_close`, the set business-rules.md says are "never mixed into
in-period totals") gives all 4 buckets real content:

- **17 rows**: `is_opening_balance=true`, present in the full table.
  Matches mission 04's 17 `OPENING_BALANCE` rows exactly.
  `bucket=intentionally_excluded, cause=opening_balance`.
- **200 rows**: `is_post_close=true`, present in the full table. Matches
  mission 04's exploration (`is_post_close=200`) exactly.
  `bucket=intentionally_excluded, cause=post_close`.
- **2 rows**: no flags, absent from the full `fact_gl_line` table
  entirely. The 1 unbalanced document mission 04/05 already exclude.
  `bucket=missing_in_fact, cause=unbalanced_document`.

17 + 200 + 2 = 219, matching the "excluded from close-eligible" total
exactly. Every row explained, `unknown` = 0%.

**Two causes have no real case to derive their logic from:**
`closing_entry` (0 `CL` documents exist in P01, already known from
mission 04) and `reversal_pair`. Checked whether the one document this
ticket excludes overlaps with any detected reversal pair: it doesn't.
Unlike `opening_balance`/`post_close`, there's no `is_reversal_pair`
column to key off - a reversal document, once loaded, is a completely
ordinary row in `fact_gl_line`, present and matching, same as any other
transaction. What condition should make a row read as
`intentionally_excluded, reversal_pair` instead of just "matched, no
mismatch" is a real open question, not something derivable from P01's
data. See Human approvals.

## Desired outcomes

- `recon_mismatch` table in `warehouse.duckdb`: one row per grain-level
  difference between `stg_gl` and the close-eligible subset of
  `fact_gl_line`, for company 1000 FY2024 P01 - `company_code,
  document_id, line_number, fiscal_year, fiscal_period, bucket, cause,
  gap` (`gap = stg_local_amount - fact_local_amount`, `NULL`/0 handled
  via `COALESCE`).
- Every row has exactly one bucket and one cause, both from the closed
  enums in `docs/definitions.md`. No cause invented inline.
- Console summary: count per bucket, count per cause, `unknown`
  percentage (must print even when 0%, not skip the line).

## Deterministic checks

- [ ] Every `recon_mismatch` row's `bucket` is one of the 4 listed
      values; every `cause` is one of the enum's ~13 values.
- [ ] `bucket=intentionally_excluded` rows only ever carry
      `cause IN (opening_balance, closing_entry, post_close,
      out_of_scope_period, reversal_pair)`, never anything else
      (docs/definitions.md's pairing rule).
- [ ] The 2 known `missing_in_fact`/`unbalanced_document` rows and the
      217 known `intentionally_excluded` rows (17 `opening_balance`, 200
      `post_close`) appear exactly, not approximately.
- [ ] `unknown` is 0% for this period (matches the exploration; nothing
      unexplained).
- [ ] `gap` for every row is computed from `stg_local_amount -
      fact_local_amount`, never asserted, and uses `ABS(gap) > 0.01`
      wherever it gates a bucket decision, never `=` on floats.
- [ ] A synthetic row proves the `closing_entry` cause path fires
      correctly, since no real `CL` document exists in P01 to test
      against.
- [ ] Whatever `reversal_pair` trigger condition gets approved (see
      Human approvals) has both a real-data check if one exists, and a
      synthetic-row proof regardless.
- [ ] Re-running the build twice gives an identical `recon_mismatch` table.

## Non-deterministic checks

| Check | Who | How an agent verifies |
|---|---|---|
| the close-eligible-subset framing is the right reading of "FULL OUTER JOIN stg_gl to fact_gl_line", not a workaround | you | agent shows both readings side by side (this mission's Exploration) and that the literal one leaves 3 of 4 required buckets permanently empty, as the basis for preferring the broader one |

## Non-goals

- Not deciding `out_of_scope_period`'s trigger condition. No row in
  company 1000 FY2024 P01 is out of the P01-P03 mapping scope by
  definition (`stg_gl` for P01 alone can't contain an out-of-scope
  document); this cause is #11's territory (FY2025 P02 stray rows).
- Not writing `reports/period_2024-01.md`. #9.
- Not backfilling P02/P03 (#10) to get more `reversal_pair`/
  `closing_entry` real cases before this ticket's cutoff. Escalating the
  gap now, not waiting for more scope to make it easier.
- Not re-deriving `unbalanced_document`/`opening_balance`/`post_close`
  logic independently. This mission reads `dq_violations` and
  `fact_gl_line`'s existing flags, doesn't recompute what #4/#5 already
  established.

## Human approvals

**Before build - the two ungrounded causes:**

- **`closing_entry`**: propose keying it off `is_closing_entry`, exactly
  parallel to `opening_balance`/`is_opening_balance`. No real case to
  confirm against, but the mechanism already exists in `fact_gl_line`
  (mission 04 built the flag, just never had a `CL` document to set it
  on). Low-risk to approve on the parallel alone.
- **`reversal_pair`**: no parallel mechanism exists. Two candidate
  designs, needs a choice before any code:
  1. Never fires within a single period's `recon_mismatch`. A reversal
     pair explains a *cross-period* pattern (mission 07: 326 pairs cross
     a period boundary), which is a #9/#10 concern once more than one
     period is in scope, not a same-period stg-vs-fact difference. Build
     nothing for it now beyond the enum already allowing it; revisit
     when #10 backfills P02/P03.
  2. A row whose document is part of a detected reversal pair
     (`recon_reversal_pairs`, either side) gets reclassified from
     "matched" to `bucket=intentionally_excluded, cause=reversal_pair`
     even when `stg_gl` and `fact_gl_line` agree exactly, so a reader of
     `recon_mismatch` sees *why* a large-looking transaction is there
     (it's half of a pair) instead of it looking like ordinary,
     unexplained activity.

**Before the output is used (#9+):**

- you rule on `reversal_pair`'s design (above), spot-check the 219 known
  `intentionally_excluded`/`missing_in_fact` rows, comment "approved" on #8

## Retro

Filled after the mission closes.
