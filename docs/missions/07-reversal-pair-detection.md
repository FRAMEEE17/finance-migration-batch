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

`notebooks/07-reversal-pair-detection.ipynb`, extended past the initial
pass with two more real findings surfaced while building (below). Scope:
company 1000, FY2024, any pair where the original or the reversal falls
in P01-P03 (ticket 3's mapping scope, not ticket 4/5/6's P01-only
`fact_gl_line` - this detects a text pattern in `stg_gl`, unrelated to
what's been period-loaded so far).

- **1,025 reversal pairs** in scope. Widening from "reversal in P01-P03"
  to "either side in P01-P03" added 126 pairs whose original posts in
  P01-P03 but whose reversal lands in P04 (all 126, checked directly).
  Narrowing to "both sides in scope" would have silently dropped the
  reversal side of these real pairs.
- The convention holds with zero exceptions across the full unscoped
  company-1000 population (4,276 `REV-` documents): `reference`'s
  embedded id always matches `header_text`'s wording. Zero
  reversal-of-a-reversal chains, zero originals reversed more than once,
  checked against all 4,276, not just the 1,025 in scope.
- **The original net-zero design was wrong.** Comparing
  `SUM(local_amount)` between an original and its reversal is
  meaningless: any balanced document already sums its own `local_amount`
  to ~0 (debit lines positive, credit lines negative, cancelling within
  that one document), so two already-zero totals will always look like
  they "net to zero" regardless of whether the reversal is real.
- **`local_amount` doesn't re-sign on reversal documents.** Checked
  line-by-line on a matched pair: account `300080` is debited 1480.61 in
  the original (`local_amount=+1480.61`) and correctly *credited*
  1480.61 in the reversal, but the reversal's `local_amount` is *still*
  `+1480.61`, copied verbatim rather than flipped to `-1480.61`. For a
  textbook-valid pair, summing `local_amount` per account doubles the
  figure instead of cancelling it. A separate defect from #13's
  broadcast-total bug, same column.
- The real net-zero signal is whether `debit_amount`/`credit_amount`
  **swap** between the two documents (original's debit total equals the
  reversal's credit total, and vice versa). Checked: **940 of 1,025
  pairs swap correctly. 85 don't** - wildly mismatched amounts and line
  counts from their claimed original (one pair: original 8 lines/
  $26,533.62, its "reversal" 90 lines/$310,051.62). **83 of those 85
  carry an `is_fraud` or `is_anomaly` flag** - reads as a planted
  fake-reversal anomaly (the text convention matches, the economics
  don't), not a real reversal gone wrong.
- **326 of 1,025 pairs cross a period boundary** (200 within P01-P03,
  126 from the scope-widening above). The pair table needs both sides'
  `fiscal_year`/`fiscal_period` as separate columns, not one shared
  period.

## Desired outcomes

- `recon_reversal_pairs` table in `warehouse.duckdb`: one row per
  detected pair - `original_document_id`, `reversal_document_id`,
  `original_fiscal_year`, `original_fiscal_period`,
  `reversal_fiscal_year`, `reversal_fiscal_period`, `cross_period`,
  `original_debit_total`, `original_credit_total`,
  `reversal_debit_total`, `reversal_credit_total`, `is_net_zero`
  (the debit/credit swap check, the authoritative signal),
  `original_local_amount`, `reversal_local_amount`, `net_local_amount`
  (kept for visibility only - expected to double, not cancel, on a
  valid pair, see Exploration), `any_flagged` (`is_fraud`/`is_anomaly`
  on either side).
- Console summary after building: pair count, cross-period count,
  `is_net_zero` true/false split, flagged count among the false ones.
- A code comment at the detection query citing ADR-0004's "this rule
  breaks if the text convention changes" warning, per issue #7's AC.

## Deterministic checks

- [x] `recon_reversal_pairs` row count == 1,025.
- [x] No duplicate `(original_document_id, reversal_document_id)` key.
- [x] Every `original_document_id` in the table has `reference NOT LIKE
      'REV-%'` in `stg_gl` (a reversal is never mistaken for an original).
- [x] `is_net_zero` split matches the exploration exactly: 940 true, 85
      false, not approximately.
- [x] 3 synthetic pairs (same-period zero, cross-period zero, genuine
      non-zero) prove the swap-tolerance arithmetic itself, since no
      single real pair distinguishes same-period from cross-period on
      this axis.
- [x] A synthetic duplicate-reversal row collapses to one pair, and a
      synthetic self-reversal (`reversal_document_id ==
      original_document_id`) is excluded, proving the detection query's
      guards rather than trusting the real data's cleanliness alone.
- [x] Re-running the build twice gives an identical `recon_reversal_pairs`
      table.

## Non-deterministic checks

| Check | Who | How an agent verifies |
|---|---|---|
| the 326 cross-period pairs don't need special handling beyond recording both periods | you | agent lists a handful, shows the gap between original and reversal period is never more than a period or two, flags if any look unusually distant |
| the 85 `is_net_zero=false` pairs are correctly read as planted anomalies, not a detection bug | you | the 2 of 85 that are *not* flagged: `67d0c630...`→`35959075...` ($321,461.44 vs $2,879.44) and `a1223a1b...`→`f3676c5e...` ($26,533.62 vs $310,051.62). Neither `is_fraud` nor `is_anomaly` on either side of either pair - the "planted anomaly" read doesn't cover these two, worth a second look |

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

- scope widened mid-mission to "either side in P01-P03" (was originally
  "reversal in P01-P03"), approved: filter company/year/period where at
  least one side is in scope; a pair whose original is in scope must
  show its reversal side even when the reversal itself posts later
- `recon_reversal_pairs` schema: pair key
  `(original_document_id, reversal_document_id)`, both sides' periods
  tracked separately, `is_net_zero` on the debit/credit swap (not
  `local_amount`), `cross_period` stored rather than recomputed downstream
- the 85 `is_net_zero=false` pairs stay as rows, flagged, never filtered
  (ADR-0003); not excluded from `recon_reversal_pairs` entirely
- 4 synthetic-test lines: same-period net-zero, cross-period net-zero,
  genuine non-zero net, and a duplicate/self-reversal that must not
  produce a second pair

**Before the output is used (#8+):**

- you spot-check a handful of the 326 cross-period pairs and the 2
  unflagged `is_net_zero=false` pairs named above, confirm the 940/85
  split looks right, comment "approved" on #7

## Retro

Two designs changed mid-build, both caught by testing the check before
trusting it, not by the real data looking wrong:

1. The original plan compared `SUM(local_amount)` between original and
   reversal. It would have shown `0` for literally any pair, valid or
   not, because any balanced document already nets its own
   `local_amount` to ~0. A check that always passes isn't a check.
2. `local_amount` doesn't re-sign on reversal documents - copied
   verbatim from the original instead of flipping with the debit/credit
   swap. Discovered by reading one pair's lines side by side, not by a
   query flagging it first.

The durable rule this adds: **before trusting a "does X net to zero"
check, verify it can fail.** Construct a case it should reject and
confirm it does, before pointing it at real data - a check that only
ever sees passing cases doesn't prove the logic is right, it proves the
data happens to be clean (or, here, that the logic was measuring
something that's always zero regardless).

Also found: 20 documents' `local_amount` and reversal documents'
`local_amount` are two different defects in the same column, not one.
Worth remembering for #8/#9: `local_amount` needs a case-by-case read,
not a single blanket caveat.

