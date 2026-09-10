# Mission 06: Account-level reconciliation (2024-01)

- **Signal:** issue #6. No `Blocked by:` line in the issue itself, but it
  reads `fact_gl_line` and `dq_violations`, both owned by #5. #5 is now
  approved and closed, so the numbers this mission reads are final, not
  provisional.
- **Confidence:** high on the mechanical part (`recon_period_summary`
  build). The investigative part (why P01's net isn't near zero) turned
  out to have a real, material answer, not a quick query.
- **Type:** request with an embedded investigation. Issue #6 explicitly
  asks for hypotheses tested before any transform, and the exploration
  found something bigger than a rounding note.
- **Decision:** act, bounded. Build `recon_period_summary` as specified.
  The local_amount finding below is escalated, not fixed here: fixing it
  means changing amounts, which is a business call this mission doesn't
  have the authority to make on its own (`docs/business-rules.md`: "Never
  fix totals by editing target amounts").

## Rules that apply

> "**Reconciliation baseline:** no separate legacy-system file exists,
> and none is fabricated. Compare `stg_gl` (raw, as-loaded) vs
> `fact_gl_line` (mapped, deduped, DQ-checked, period-scoped)."
> (docs/business-rules.md)

> "Close **totals** (what's reported to finance) use `local_amount`...
> Never sum `transaction_amount` to close a period." (docs/business-rules.md)

> "Reconciling differences or changing a business rule is careful work.
> Slow down for it." (docs/business-rules.md, working rules)

> "`local_amount_imbalance`: A finding on a document that balances on
> `debit_amount − credit_amount` but whose `local_amount` does not net to
> zero (currency-conversion rounding). Reported, never a publish blocker."
> (CONTEXT.md) - this parenthetical turns out to be right for 3 of the 23
> logged cases and wrong for 20 of them. See Exploration.

## Exploration

`notebooks/06-account-level-reconciliation.ipynb`. Issue #6 asks for two
hypotheses, tested with queries, before any transform:

**H1: the ledger doesn't balance on debit/credit.** Rejected.
`SUM(debit_amount) - SUM(credit_amount)` across the whole P01 scope is
`90.0`, exactly the gap from the 1 document `fact_gl_line` already
excludes as `unbalanced_document` (ticket 5). Everywhere else, the ledger
balances correctly.

**H2: something is wrong with `local_amount` on specific documents.**
Confirmed. 20 documents (of 3,518) account for the entire
`97,144,587.1` period net. All 20 have an unusually high line count
(18-81 lines, versus 2-4 for a typical document). Looking at the biggest
one: 36 debit lines, each with a different `debit_amount`, but every one
carries the identical `local_amount` value, `1,189,904.91`, which turns
out to be the *document's total*, not that line's amount. The single
credit line correctly shows `-1,189,904.91`. Sum the document:
`35 × 1,189,904.91 = 41,646,671.85`, exactly matching that document's
contribution to the period net. This reads as a document-level total
broadcast onto every line during source generation, not a rounding
artifact, and not something `is_fraud`/`is_anomaly` flags (only 2 of the
20 carry either).

These 20 documents were not newly discovered here. All 20, plus 3 more at
$0.01-0.02 (genuine rounding), are already in ticket 5's
`local_amount_imbalance` finding (23 rows total). What changed is
understanding *why* 20 of them are large: `docs/definitions.md` /
`CONTEXT.md` currently describe this cause as "(currency-conversion
rounding)", accurate for 3 rows, misleading for the other 20.

**Consequence for this mission's actual deliverable:** the account-level
`stg_gl` vs `fact_gl_line` comparison will be almost entirely clean. 500
of 502 accounts match exactly; the other 2 come from the 1 already-
excluded unbalanced document. `fact_gl_line` inherits the same
`local_amount` values `stg_gl` has, defect included, because nothing in
#4/#5 touches that column. The interesting finding isn't a stg/fact
mismatch. It's that the close total itself rests on ~$97M of
`local_amount` that doesn't mean what the column name says it means.

## Desired outcomes

- `recon_period_summary` table in `warehouse.duckdb`: one row per
  `(gl_account, fiscal_year, fiscal_period)` in scope, with `stg_total`,
  `fact_total`, `gap` (all on `local_amount`), built straight from
  `stg_gl` and `fact_gl_line`.
- A written conclusion (this mission spec's Exploration section,
  expanded into `docs/mapping-review.md`-style detail in
  `docs/period-close-notes/2024-01-net-local-amount.md` or similar) that
  states the H1/H2 finding, the 20 affected documents, and recommends
  what should happen next, without implementing a fix.
- `docs/definitions.md` / `CONTEXT.md`'s `local_amount_imbalance`
  description corrected: it isn't always rounding.

## Deterministic checks

- [ ] `recon_period_summary` row count == distinct `(gl_account,
      fiscal_year, fiscal_period)` combinations in scope across `stg_gl`
      UNION `fact_gl_line`.
- [ ] `gap = stg_total - fact_total` for every row, computed, not asserted.
- [ ] Exactly 2 accounts have `ABS(gap) > 0.01`, both attributable to the
      1 known `unbalanced_document`. Every other account's gap is 0.
- [ ] The 20 large-magnitude `local_amount_imbalance` documents are named
      explicitly in the written conclusion, not folded into a single
      "misc" number.
- [ ] Re-running the build twice gives identical `recon_period_summary`
      contents (same idempotency bar as #4/#5).

## Non-deterministic checks

| Check | Who | How an agent verifies |
|---|---|---|
| the document-total-broadcast explanation for the 20 documents is the right read, not a coincidence | you | agent shows the full line-by-line detail of 2-3 more of the 20 (not just the biggest one) so the pattern isn't cherry-picked from a single example |
| what to actually do about the ~$97M `local_amount` defect (escalate as a known issue for #9's report, open a new ticket to investigate root cause with the data source, or something else) | you (business call) | agent lays out the options, does not pick one |

## Non-goals

- Not fixing `local_amount` on the 20 documents. `stg_gl` is raw and
  immutable; even a "corrected" value in `fact_gl_line` would be editing
  a target amount, which `docs/business-rules.md` rules out without an
  explicit, separate decision.
- Not building `recon_mismatch` (document-level, bucket + cause). #8.
- Not writing `reports/period_2024-01.md`. #9.
- Not deciding whether the ~$97M belongs in the close total as-is, gets
  excluded, or gets flagged as unreliable pending investigation. That's
  the business call in Non-deterministic checks, not this mission's to
  make.

## Human approvals

**Before build:**

- issue #5 approved and closed. `fact_gl_line`/`dq_violations` are final
  for this scope, not provisional
- `recon_period_summary` schema and grain as described above
- the H1/H2 exploration stands as the "hypotheses tested" deliverable
  issue #6 asks for; no further hypothesis needed before building the
  table itself

**Before the output is used (#7+):**

- you rule on what happens to the ~$97M finding (see Non-deterministic
  checks), spot-check `recon_period_summary`'s 2 non-zero accounts,
  comment "approved" on #6

## Retro

Filled after the mission closes.
