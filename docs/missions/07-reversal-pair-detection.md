# Mission 07: Reversal-pair detection

- **Signal:** issue #7. No `Blocked by:` line; operates on `stg_gl`
  directly, doesn't depend on `fact_gl_line`/`dq_violations`.
- **Confidence:** high. ADR-0004 already made the detection-method
  decision (text convention, not a status column); this mission is
  building what that ADR already committed to.
- **Type:** request. Detection and reporting only. Issue #7 is explicit:
  "no deletes", both sides of every pair stay in the data untouched.
- **Decision:** act. Build the pair table and the per-pair report.

## Rules that apply

> "**Reversals:** no `is_cancelled` column exists. Detect reversal
> documents by convention (`reference` starts `REV-...`, `header_text`
> reads "Reversal of `<document_id>`"), link to the original, report as
> a "reversal pairs" bucket. Never delete either side." (docs/business-rules.md)

> "No `is_cancelled` or `reversal_of_doc_id` column exists.
> `predecessor_line_id` is populated for only 13 of 40,386 rows in scope,
> too sparse to build a rule on... Decision: parse this convention...
> Consequence: this rule breaks if the text convention changes upstream."
> (ADR-0004)

## Exploration

`notebooks/07-reversal-pair-detection.ipynb`. Scope: company 1000, FY2024
P01-P03 (ticket 3's mapping scope, not ticket 4/5/6's P01-only
`fact_gl_line` - this detects a text pattern in `stg_gl`, unrelated to
what's been period-loaded so far).

- **899 reversal documents** (`reference LIKE 'REV-%'`) in scope.
- The convention holds with zero exceptions: `reference`'s embedded id
  always matches `header_text`'s "Reversal of `<id>`" wording, on every
  one of the 899.
- All 899 originals exist in scope. Zero reversal-of-a-reversal chains,
  zero originals reversed more than once.
- All 899 pairs net to ~0 on `local_amount`. Issue #7 asks for pairs that
  don't net to about 0 to be listed separately; there are none in this
  scope, so that path needs a synthetic-row proof, same pattern as
  earlier tickets' zero-real-case checks.
- **200 of 899 pairs cross a period boundary**: the original posts in
  one period, the reversal in a later one. Only 699 share the same
  `fiscal_period` as their original. The pair table needs both sides'
  `fiscal_year`/`fiscal_period` as separate columns, not one shared
  period.

## Desired outcomes

- `recon_reversal_pairs` table in `warehouse.duckdb`: one row per
  detected pair - `original_document_id`, `reversal_document_id`,
  `original_fiscal_year`, `original_fiscal_period`,
  `reversal_fiscal_year`, `reversal_fiscal_period`, `original_local_amount`,
  `reversal_local_amount`, `net_amount`, `is_net_zero` (boolean, `ABS(net_amount) <= 0.01`).
- Console summary after building: pair count, count of non-zero-net pairs
  (0 today, still computed and printed, not assumed), total original
  amount reversed.
- A code comment at the detection query citing ADR-0004's "this rule
  breaks if the text convention changes" warning, per issue #7's AC.

## Deterministic checks

- [ ] `recon_reversal_pairs` row count == 899.
- [ ] Every `original_document_id` in the table has `reference NOT LIKE
      'REV-%'` in `stg_gl` (a reversal is never mistaken for an original).
- [ ] `net_amount` for every row == `original_local_amount +
      reversal_local_amount`, computed, not asserted.
- [ ] `is_net_zero` is `true` for all 899 current rows (matches the
      exploration finding exactly, not approximately).
- [ ] A synthetic pair with a deliberately non-zero net proves
      `is_net_zero` correctly comes out `false` for it, since no real
      case exists to test against.
- [ ] No row in `stg_gl` that is part of a detected pair (either side) is
      absent afterward - `stg_gl`'s row count is unchanged by this
      mission (nothing deleted, matching issue #7's AC literally).
- [ ] Re-running the build twice gives an identical `recon_reversal_pairs`
      table.

## Non-deterministic checks

| Check | Who | How an agent verifies |
|---|---|---|
| the 200 cross-period pairs don't need special handling beyond recording both periods | you | agent lists a handful of the 200, shows the gap between original and reversal period is never more than a period or two, flags if any look unusually distant |

## Non-goals

- Not editing `docs/definitions.md`'s mismatch-cause enum to add anything
  new. `reversal_pair` is already a listed cause; this mission produces
  the table that cause will reference in #8, not the classification
  logic itself.
- Not building `recon_mismatch` (document-level, bucket + cause). #8.
- Not deciding how a cross-period reversal pair should be treated in
  `reports/period_YYYY-PP.md` when the two periods are reported
  separately (does the reversal's period show it, does the original's,
  both?). Flagged for #9, not decided here.
- Not detecting reversals outside company 1000 / FY2024 P01-P03. Same
  scope boundary the rest of the project uses; broader scope is a
  backfill-ticket concern (#10), not this one's.

## Human approvals

**Before build:**

- scope is company 1000, FY2024 P01-P03 (stg_gl-wide), not tied to
  `fact_gl_line`'s current P01-only state
- `recon_reversal_pairs` schema as listed above, both sides' periods
  tracked separately
- synthetic-row proof for the non-zero-net path, since no real case
  exists

**Before the output is used (#8+):**

- you spot-check a handful of the 200 cross-period pairs, confirm the
  899/899 net-zero result looks right, comment "approved" on #7

## Retro

Filled after the mission closes.
