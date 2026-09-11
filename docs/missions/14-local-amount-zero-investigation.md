# Mission 14: local_amount = 0 investigation

- **Signal:** issue #14, no blocker. Split out from mission 13/ADR 0006.
- **Confidence:** high on the two-mechanism split (query-verified against
  the whole file). Low on Group B's actual trigger - no single field
  closes it the way `source = 'AB'` closed ticket 13.
- **Type:** investigation. `stg_gl` is raw and immutable; nothing in
  this pipeline gets fixed by this mission, same rule as mission 13.
- **Decision:** investigate. Started from the forced test case
  (`115020`/`205020`) and the falsified `automated`/`adjustment`
  correlation issue #14 was filed against, then tested every field the
  issue asked for.

## Rules that apply

> "A predictor confirmed by query against the whole file (4 companies,
> both fiscal years), not a correlation restated from this ticket."
> (issue #14)

> "Classified: source-side defect, an intentional memo/statistical
> account design, or a feed that never writes `local_amount` at all -
> these need different responses." (issue #14)

> "Not closed on a source/document_type breakdown table alone - the
> forced test case above has to be explained." (issue #14)

## Exploration

`notebooks/14-local-amount-zero-investigation.ipynb`. All queries
against `stg_gl`, no company/year/period filter, same as mission 13.

**The 931 rows split into two mechanisms, not one.** Computed
per-`gl_account` defect rate across the whole file (every row for that
account, not just the flagged ones):

- **Group A - 10 accounts, 100.00% defect rate, zero exceptions:**
  `115010`, `115020`, `115021`, `115030`, `205010`, `205020`, `205021`,
  `205030` (317 rows total between them - the forced test case pair and
  its siblings, plus 4 more the same shape), and `4800`/`4810` (1 row
  each, too thin to weigh the same as the other 8). Every one of these
  accounts reads `local_amount = 0` on **every single row** where
  debit or credit is nonzero, regardless of `created_by`,
  `document_type`, company, or period. `115xxx`/`205xxx` pairs asset
  against liability - reads as an intercompany clearing pair structure
  the same way `map_account.csv`'s own `account_role=clearing_pair`
  already tags 6 of the 10 (`115020`/`115021`/`115030`/`205020`/
  `205021`/`205030` - ticket 3's mapping review). `115010`/`205010`
  weren't in that tag list despite showing the identical 100% pattern
  (80 and 77 rows respectively, not thin samples) - the mapping file's
  `dq_flag` coverage missed 2 real members of the same family.
  `account_description` is `None` for all 10 in the source, so this
  reads as structural (an account whose nature is "the local_amount
  concept doesn't apply") rather than confirmed from a label.
- **Group B - 28 accounts, 614 rows, low defect rate (0.06%-9.72% per
  account):** every other account in the 931-row set. `gl_account`
  alone doesn't predict these - the same accounts return the correct
  `local_amount` the overwhelming majority of the time. Narrowed to
  `created_by IN ('SYSTEM', 'IC_GENERATOR')` (100% recall, still only
  ~11% precision) and checked fiscal period distribution: period 12
  shows a mild skew (107 defective / 635 total = 16.9%, versus 5-9% for
  periods 1-11), not sharp enough to call a trigger. `is_anomaly=true`
  covers 35 of the 773 non-clearing rows across 7 different
  `anomaly_type` values, too scattered to be the cause. No field tested
  reaches anywhere near `source = 'AB'`'s zero-exception bar.

**The forced test case is explained.** `115020` (all debit) /
`205020` (all credit), `pair_id=115020_205020` - both in Group A, both
100% defect rate, both already tagged `account_role=clearing_pair` in
`map_account.csv`. Confirms the mission's own required check before
any other finding counted.

**Fields checked with no signal, dataset-wide:** `currency` (100% USD
on the defect set, but USD dominates the whole file - not
distinguishing), `exchange_rate` (100% `1.0`, same issue), `is_manual`
(100% `false`), `is_fraud`/`is_post_close` (100% `false`), reversal
overlap (`reference LIKE 'REV-%'`: 0 rows, confirmed by query),
`transaction_amount` (100% `NULL` on the defect set, but that's true
for 97% of the whole file - not distinguishing), `predecessor_line_id`
(100% `NULL`), `lettrage` (100% `NULL`, same as the whole `R2R`
population), `approver` (100% `NULL` - consistent with system-generated
postings needing no human sign-off, not a cause on its own).

## Desired outcomes

- Group A classified: **intentional memo/statistical account design**,
  not a defect. 10 accounts, structurally never carry a real
  `local_amount`. Candidate for the same treatment `catch_all` got in
  ADR-0005 - a named status/flag other checks and reports can exclude
  by, not a silent gap.
- Group B classified: **unresolved**. Real, sporadic, correlates with
  system-generated postings but no confirmed trigger. Not the same
  shape as ticket 13's clean root cause and shouldn't be reported as
  if it were.
- A decision recorded on each group separately - they don't share a
  fix path, so one ruling doesn't have to cover both.
- `map_account.csv`'s `dq_flag` gap (`115010`/`205010` missing the tag
  its 4 siblings have) surfaced for you to decide whether it gets
  corrected now or tracked as its own small follow-up.

## Deterministic checks

- [x] Group A's 100% defect rate is reproducible from a single query
      against `stg_gl` with no company/year/period filter, committed as
      an executed notebook cell
      (`notebooks/14-local-amount-zero-investigation.ipynb`).
- [x] The forced test case (`115020`/`205020`) is explained: both are
      Group A, both 100% defect rate, both already tagged
      `account_role=clearing_pair` in `map_account.csv`.
- [x] No row in `stg_gl`, `fact_gl_line`, or any `recon_*`/`dq_*` table
      is modified by this mission. `src/checks.py` still 56/56 after
      this mission's queries, `git status` shows no warehouse-adjacent
      file touched.

## Non-deterministic checks

| Check | Who | How an agent verifies |
|---|---|---|
| whether Group A really is intentional design versus a defect that happens to be 100% consistent because it was planted that way (showcase dataset) | you | agent lays out the account-code pattern and asset/liability pairing, you judge what it implies |
| whether Group B is worth further investigation now or should stay open as a known-unresolved item, given no field closes it | you | agent shows what was tested and what's left untested, you decide the priority |

## Non-goals

- Not touching `stg_gl` or any loaded table. This mission only reads.
- Not deciding either group's fix unilaterally. Both decisions stay
  open until you rule on them.
- Not chasing Group B further than the fields issue #14 explicitly
  asked to test, once none of them closed it - flagging as unresolved
  is a valid outcome of an investigation, not a stopping point to push
  past without your input.

## Human approvals

**Before build:** none needed - read-only investigation, nothing to
approve before the fact.

**Before the output is used:**

- you rule on Group A: intentional design, formalized (a status/flag,
  same pattern as `catch_all`), or something else
- you rule on Group B: source-side investigation continues, downstream
  documents it as unresolved, or something else
- you decide whether the `map_account.csv` `dq_flag` gap
  (`115010`/`205010`) gets fixed now or tracked separately

**Ruling:** Group A confirmed for exactly 8 of its 10 accounts - the 4
`115xxx`/`205xxx` pairs, not `4800`/`4810` (1 row each, not enough
evidence). No new `status` value; a new `local_amount_expected` column
instead, `false` on these 8, `true` everywhere else. `4800`/`4810` stay
with Group B, unresolved. `115010`/`205010` get added to
`map_account.csv` now (not deferred) under a relaxed
`map_account_covers_scope` check (coverage, not exact equality) since
they have zero activity in company 1000 and would otherwise fail the
old exact-match check. Group B: recorded as unresolved, not chased
further this round. Full writeup:
`docs/adr/0007-local-amount-zero-clearing-pairs-by-design.md`.

## Retro

Group A's 100%-precision, zero-exception split from Group B only showed
up by computing defect rate **per account against its own total
activity**, not by testing fields against the flagged rows the way
`source = 'AB'` was found in mission 13. The 931-row set is two
different phenomena with two different evidence shapes; treating it as
one correlation-hunting exercise (the `automated`/`adjustment` false
start) would have kept missing that split.

Before touching `quality_gate.py`, checked whether it actually needed
to change: it didn't. `local_amount_imbalance` sums `local_amount` per
document, and Group A's value is always exactly `0.0` - adding zero to
a sum never changes it, so the check was never miscounting these lines
in the first place. Worth remembering: an instruction to "stop a check
from doing X" is worth verifying the check is actually doing X before
writing the fix.

One real bug came out of implementing the ruling, not from investigating
it: `map_account.csv`'s writer joined columns with a bare `",".join(...)`,
no quoting. The `notes` text for the newly-added out-of-scope pair
contained a comma, and would have silently shifted every later column
on that row the moment anyone read the file back - caught immediately
by re-parsing the file after writing it, not by code review. Fixed by
switching `src/build_mapping.py` to Python's `csv.writer`, which is
correct for every future note too, not just this one.

`map_account_covers_scope`'s exact-equality check turned out to be
stricter than the project actually needed: the real invariant is "every
scope account has a mapping row," not "the mapping file contains
nothing else." Relaxed to coverage rather than working around it with a
special case for this one pair - the next out-of-scope account that
needs documenting for the same reason won't need its own carve-out.
