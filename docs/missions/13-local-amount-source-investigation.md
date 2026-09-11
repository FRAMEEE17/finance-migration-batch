# Mission 13: local_amount source-data investigation

- **Signal:** issue #13, no blocker. Split out from ticket 6's finding
  and escalated with 3-period evidence in mission 10.
- **Confidence:** high on the root cause (one column value predicts the
  defect almost perfectly, checked against every document in the whole
  source file, not a sample). Medium on the decision this mission has
  to record, since that's a business call, not something derivable from
  the data.
- **Type:** investigation. `stg_gl` is raw and immutable; nothing in
  this pipeline gets fixed by this mission. The deliverable is a root
  cause, a confirmed scope, and a recorded decision on what downstream
  consumers (this pipeline included) do about it.
- **Decision:** investigate. Query the full source file (all 4
  companies, both fiscal years, every period) - ticket 6 and mission 10
  only ever looked at company 1000's 3 in-scope periods.

## Rules that apply

> "root cause identified: why does `local_amount` get the document
> total instead of a per-line amount on high-line-count documents
> specifically" (issue #13)

> "confirmed whether this affects periods/companies beyond the P01
> scope checked here" (issue #13)

> "a decision recorded on whether/how the source regenerates corrected
> `local_amount` values, or whether downstream consumers need a
> documented workaround instead" (issue #13)

> "Never fix totals by editing target amounts." (docs/business-rules.md)

## Exploration

All queries run directly against `stg_gl`, which loads the full source
parquet (648,801 rows, all 4 companies, FY2024 and FY2025) regardless of
this pipeline's declared scope - the investigation isn't limited by
what `fact_gl_line` happens to contain.

**Ticket 6's original hypothesis was "high line count causes the
defect." That doesn't hold up against the full file.** Every source
value that reaches 18+ line documents was checked, not just `AB`:

| source | docs | avg lines | max lines | docs with 18+ lines |
|---|---|---|---|---|
| RV | 24,179 | 3.5 | 202 | 248 |
| KR | 18,265 | 3.4 | 192 | 154 |
| DR | 15,162 | 3.4 | 212 | 155 |
| SA | 13,839 | 3.4 | 200 | 112 |
| ... (6 more sources, same shape) | | | | |

Every one of those sources produces high-line-count documents
routinely, and almost none of them show the defect. High line count is
common; the defect isn't. Line count is a correlate, not the cause.

**`source = 'AB'` is the actual predictor.** Grouped every document in
the whole file by whether it balances on debit/credit but doesn't net
to zero on `local_amount` (the exact `local_amount_imbalance` predicate
from `src/quality_gate.py`, applied dataset-wide instead of scope-only):

- 1,123 documents in the entire file have `source = 'AB'`. All 1,123
  are flagged. Zero exceptions, zero false negatives.
- `source = 'AB'` documents range from 31 to 155 lines (average 57).
  There is no low-line-count `AB` document to check against - every
  `AB` document is structurally a high-line-count one, which is why
  ticket 6's line-count hypothesis looked right from inside the P01
  scope. It's downstream of the real cause, not the cause itself.
- Of the ~1,132 defect documents dataset-wide, 1,123 are `AB`. The
  remaining ~9 are unrelated: re-checked P01's own 20-document finding
  from mission 06/10 directly - 19 of the 20 are `source = 'AB'`; the
  20th (`source = 'RV'`, net `0.02`) is one of the 3 already-known
  genuine sub-cent rounding cases from mission 06, not this defect.
  P02's 27 and P03's 36 are `source = 'AB'` with zero exceptions.
- `source_system`, `document_type`, `created_by`, `currency`, and
  `is_manual` were all checked too (grouped, counted, percent-defective
  per value). None of them isolate the defect the way `source` does -
  the mild skew each shows is just `AB` documents happening to spread
  across those dimensions, not a second real cause.

**Scope is the whole file, not company 1000 / FY2024.** Same
`local_amount_imbalance` predicate, no company or year filter:

| company_code | fiscal_year | defect docs | net local_amount |
|---|---|---|---|
| 1000 | 2024 | 296 | 3,980,025,369.82 |
| 1000 | 2025 | 7 | 127,790,531.40 |
| 2000 | 2024 | 272 | 1,625,495,326.05 |
| 2000 | 2025 | 4 | 2,364,434.23 |
| 2100 | 2024 | 278 | 1,957,924,352.02 |
| 2100 | 2025 | 5 | 101,185,326.02 |
| 3000 | 2024 | 264 | 1,706,873,684.22 |
| 3000 | 2025 | 6 | 21,090,585.57 |

**1,132 documents dataset-wide, `9,522,749,609.33` net `local_amount`
total.** All 4 companies, both fiscal years. `source = 'AB'` documents
appear in every one of FY2024's 12 periods and FY2025's period 1 (22
documents) - the defect isn't concentrated in any one period either.
For scale: total `debit_amount` across the whole file is
`45,257,592,963.24`; total `|local_amount|` is `88,542,897,320.76`. The
defect accounts for roughly a fifth of total debit activity by this
measure - material at the whole-dataset level, not an edge case.

## Desired outcomes

- Root cause on record: `source = 'AB'` predicts the defect with no
  known exception across the entire 648,801-row file. Whatever
  generates `local_amount` for `AB`-sourced postings computes one
  value at the document level and stamps it onto every debit line,
  instead of computing each line's own converted amount.
- Confirmed scope on record: all 4 companies, both fiscal years, every
  period that has `AB`-sourced activity - not a P01 or company-1000
  finding.
- A decision recorded (yours, not derived): source regeneration,
  downstream workaround, or something else. This mission does not pick
  one.
- `docs/period-close-notes/2024-01-local-amount-defect.md` gets a
  pointer to this mission rather than staying the only writeup, since
  it was written before the scope was known to be this wide.

## Deterministic checks

- [x] `source = 'AB'` accounts for every P01/P02/P03 broadcast-defect
      document already found in missions 06/10 (19/20, 27/27, 36/36 -
      the one exception is the already-known sub-cent rounding case,
      not this defect). Re-run for real in
      `notebooks/13-local-amount-source-investigation.ipynb`, executed,
      output matches exactly.
- [x] The dataset-wide defect count and total are reproducible from a
      single query against `stg_gl` with no company/year/period filter -
      committed as an executed notebook cell, not just quoted in this
      doc.
- [x] No row in `stg_gl`, `fact_gl_line`, or any `recon_*`/`dq_*` table
      is modified by this mission. `src/checks.py` still 56/56 after
      this mission's queries, `git status` shows no warehouse-adjacent
      file touched.

## Non-deterministic checks

| Check | Who | How an agent verifies |
|---|---|---|
| whether `source = 'AB'` correlating this cleanly is itself suspicious (planted rather than organic) given this is a showcase/demo dataset | you | agent lays out the correlation strength, you judge what it implies about the dataset's construction |
| which of the "Done when" decision options (source regenerates vs. documented workaround vs. something else) fits given this is a portfolio project with no real upstream system to regenerate anything from | you | same as above - a real call, not a data question |

## Non-goals

- Not touching `stg_gl` or any loaded table. This mission only reads.
- Not deciding the workaround unilaterally. The decision section stays
  open until you rule on it.
- Not re-litigating tickets 6/9/10's P01-P03 findings - those numbers
  are re-confirmed here, not redone.
- Not blocking on issue #11. That ticket's own precondition (FY2024
  reports signed off) is unrelated to this investigation finishing.

## Human approvals

**Before build:** none needed - this mission only ran read-only queries
against already-loaded data, nothing to approve before the fact.

**Before the output is used:**

- you rule on the "Done when" decision: does `source = 'AB'` regenerate
  from wherever the source system lives, or do downstream consumers
  (this pipeline, and presumably others) get a documented permanent
  workaround instead
- you confirm the dataset-wide scope finding doesn't change anything
  about the FY2024 P01-P03 reports already accepted (it shouldn't -
  this mission only reads, never writes)

**Ruling:** `AB` regenerates `local_amount` per line at the source.
This pipeline does not build a permanent downstream substitute.
Downstream may add a clearly-separate, clearly-labeled temporary column
while waiting (never overwriting `stg_gl.local_amount`, never presented
as a signed figure) - recorded in full in
`docs/adr/0006-local-amount-source-fix-not-downstream-workaround.md`,
along with the acceptance criteria for a future regenerated file. The
dataset-wide scope doesn't touch anything already accepted; nothing in
`stg_gl` or any downstream table changed.

## Retro

The line-count hypothesis from ticket 6 was reasonable given what P01
alone showed, and wrong. `source = 'AB'` is the actual predictor, with
zero exceptions across the whole 648,801-row file - checking every
source value's line-count distribution, not just the flagged
documents', is what separated correlation from cause here. Worth
remembering next time a hypothesis looks solid from inside a narrow
scope: check whether the same shape shows up in the data that *isn't*
flagged before trusting it.

One loose end surfaced but not chased down: while verifying the
acceptance criteria for a future regenerated file, checked for a
`local_amount = 0` despite nonzero debit/credit pattern. It's real (931
rows dataset-wide, 58 documents in this pipeline's own P01-P03 scope)
but correlates with `source IN ('automated', 'adjustment')`, not `AB`,
and touches zero reversal documents - a different defect shape than
this mission's broadcast pattern. Recorded as an open question in ADR
0006 rather than folded into this mission's findings; whether it's
issue #13's territory or its own ticket is for you to decide, not
something this mission should assume either way.
