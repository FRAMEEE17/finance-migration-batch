# Mission 16: safe read path for daily data consumers

- **Signal:** issue #16, no blocker.
- **Confidence:** high. Every column the view needs already exists on
  `fact_gl_line`; this mission adds a filtered view and documentation,
  not new computation.
- **Type:** build, fully specified - the issue locked all 3 open
  points (what "ready" means, which column carries the primary total,
  what "period movement" excludes) before this mission started.
- **Decision:** act. A view (`fact_gl_line_ready`), a short
  consumer-facing doc, and 2 runnable SQL examples - one correct, one
  the known `AB`-broadcast trap, proven wrong with real numbers.

## Rules that apply

> "ready = recon_status='accepted', not waiting on
> local_amount_status='signed'." (issue #16 ruling)

> "not_signed periods never send local_amount as the primary total -
> debit_amount / credit_amount instead. local_amount can stay in the
> view, just never the column the docs say to SUM." (issue #16 ruling)

> "period movement excludes is_opening_balance and is_post_close;
> grain is one document line, not one account." (issue #16 ruling)

> "No dashboard, no #13 fix, no scope expansion, this view is never a
> second sign-off artifact." (issue #16, non-goals)

## Exploration

Confirmed against live data before writing any SQL:

- `fact_gl_line` already carries `is_opening_balance`,
  `is_closing_entry`, `is_post_close` as booleans - the exact 3 flags
  mission 08's `recon_mismatch` close-eligible subset already
  excludes. The issue named `is_opening_balance` and `is_post_close`
  explicitly; `is_closing_entry` is the same business rule
  (`docs/business-rules.md`: "CL: closing entry. Not in in-period
  totals.") and left out only because no `CL` document exists in the
  current P01-P03 scope to have prompted mentioning it - excluding it
  too keeps this view consistent with the one already-established
  close-eligible definition instead of drifting from it.
- `period_signoff` currently has all 3 periods at
  `recon_status='accepted'`, `local_amount_status='not_signed'` - so
  the view will include all 3 periods today, all with `local_amount`
  correctly excluded from the documented-safe column list.
- Confirmed the trap is real, not hypothetical: `SUM(local_amount)`
  on document `0a121d1e-7334-81f7-2608-9bb9a6e55fab` (source `AB`,
  P01) returns `41,646,671.85` - the document's total, broadcast
  across 37 lines - not that document's actual net position. The
  correct figure for the same document from `debit_amount`/
  `credit_amount` is a genuinely different, correct number. Both
  numbers are in the doc, not asserted.

## Desired outcomes

- `fact_gl_line_ready`: a view, `fact_gl_line` joined to
  `period_signoff`, filtered to `recon_status = 'accepted'`. Adds
  `recon_status`, `local_amount_status`, and a computed
  `is_period_movement` (`NOT is_opening_balance AND NOT
  is_closing_entry AND NOT is_post_close`) so a consumer doesn't need
  to know to combine 3 flags correctly by hand.
- `docs/how-to-query-fact_gl_line.md`: grain (one document line),
  which columns are safe to aggregate as a period total
  (`debit_amount`/`credit_amount`, always; `local_amount`, only when
  `local_amount_status='signed'`), a correct example, and the `AB`
  broadcast trap as the wrong example, both runnable with real numbers
  from Exploration.
- No new table, no new sign-off state, no dashboard.

## Deterministic checks

- [x] `fact_gl_line_ready` exists as a view (not a materialized copy -
      always current with `fact_gl_line`/`period_signoff`).
      `fact_gl_line_ready_is_a_view`.
- [x] Every row in the view has `recon_status = 'accepted'`; no row
      from a hypothetical blocked period would ever appear.
      `fact_gl_line_ready_only_accepted_periods`.
- [x] `is_period_movement` matches `NOT is_opening_balance AND NOT
      is_closing_entry AND NOT is_post_close` for every row, checked
      by query, not assumed from the view definition.
      `fact_gl_line_ready_movement_flag_correct`.
- [x] The view's row count for the current scope equals
      `fact_gl_line`'s row count for the same scope (all 3 periods are
      `accepted`, so nothing is silently dropped at the view layer).
      `fact_gl_line_ready_row_count_matches_fact`: 40,384 == 40,384.
- [x] `docs/how-to-query-fact_gl_line.md` exists, contains a `SUM(local_amount)`
      example scoped to an `AB` document, and states the real (wrong)
      number that query returns - re-run at check time, not pasted
      once and left to go stale. `how_to_query_doc_has_real_trap_example`.

## Non-deterministic checks

| Check | Who | How an agent verifies |
|---|---|---|
| the doc reads clearly to someone who has never seen this repo and just wants to query the table | you | cold read, same bar as the runbook's own non-deterministic check |

## Non-goals

- No Power BI, Tableau, or any dashboard. This view is what one would
  read later, not built here.
- Not fixing issue #13.
- Not loading FY2025 or any company beyond scope.
- Not a second sign-off artifact - `period_signoff` and the controller
  pack stay the only place a status gets recorded.

## Human approvals

**Before build:** none needed - the issue locked all 3 open points.

**Before the output is used:** you cold-read
`docs/how-to-query-fact_gl_line.md`, comment "approved" on #16.

## Retro

The view itself was a 15-line SQL statement - every column it needed
already existed, and the 3 pre-locked decisions (ready = accepted not
signed, debit/credit as primary not local_amount, movement excludes
3 flags not 2) meant there was nothing left to design, only to write
correctly.

The doc caught a real bug in itself before it shipped: the "correct
example" query was drafted assuming it would return a clean `0.00` for
every period, and P01/P02 actually return `-0.00` - the same DuckDB
parallel-SUM floating-point quirk mission 10 already found and fixed
in `build_period_report.py`. This doc's own example query wasn't
routed through that fix (it's a documentation example, not pipeline
code), so it surfaces the quirk directly. Fixed by stating the real
output including the sign, with a one-line explanation, instead of
quietly rounding the claim to what looked cleaner - exactly the kind
of thing this whole project exists to not do.

`is_closing_entry` got added to the movement-exclusion flag even
though the issue only named `is_opening_balance` and `is_post_close` -
it's the same business rule (`docs/business-rules.md`'s `CL` doc-type
exclusion) and no `CL` document exists in the current scope to have
prompted mentioning it. Included for consistency with the
already-established close-eligible definition (mission 08) rather than
inventing a narrower one that would drift from it.
