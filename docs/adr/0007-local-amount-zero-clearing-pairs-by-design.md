# local_amount = 0 on clearing-pair accounts is by design, not a defect

**Status:** accepted

`docs/missions/14-local-amount-zero-investigation.md` (issue #14) found
the 931 rows where `local_amount = 0` despite a nonzero
`debit_amount`/`credit_amount` split into two mechanisms:

- **Group A**, 317 rows across 10 `gl_account` codes, every one of them
  at exactly 100.00% defect rate dataset-wide, zero exceptions.
- **Group B**, 614 rows across 28 other codes, each at a low defect
  rate (0.06%-9.72%), no field tested closes it cleanly.

This ADR rules on Group A only.

## Decision

The 4 pairs `115010`/`205010`, `115020`/`205020`, `115021`/`205021`,
`115030`/`205030` (8 of Group A's 10 codes - the other 2, `4800`/`4810`,
have only 1 row each in the whole file and are not confirmed by this
ruling, see below) are **intercompany clearing pairs where
`local_amount` doesn't apply by design**, not a defect. `115xxx`
(asset) pairs against `205xxx` (liability); `local_amount = 0` on every
row of every one of the 8, over the whole dataset, with no exception -
the ruling reads this as the account's nature, not as corrupted data
that happens to always corrupt the same way.

This does **not** add a new `status` value. `status='unmapped'` for all
8 stays exactly as ticket 3 originally set it for the 3 pairs it found
- `catch_all` (ADR-0005) was a genuinely new classification question
about where an account belongs in the target CoA; this is a statement
about one column's applicability to an account already otherwise
classified. Conflating the two would blur what `status` answers.

Instead: a new `map_account.csv` column, `local_amount_expected`
(`true`/`false`). `false` exactly on these 8 accounts. Every other
account, including the 2 single-purpose `clearing` accounts and both
`catch_all` codes, is `true` - a real `local_amount` bug on an ordinary
account is still `local_amount_expected=true`, this field marks what
an account structurally carries, not whether today's data is clean.

## 115010 / 205010: same family, different scope problem

`115020`/`115021`/`115030` and their `205xxx` partners all have real
activity in company 1000 - this pipeline's scope - which is why ticket
3 found them. `115010`/`205010` have **zero rows in company 1000**;
they only exist in companies 2000/2100/3000. This isn't a gap in
ticket 3's work - company 1000 was always its declared scope, and this
pair was never in it to find.

`map_account.csv` is enforced by `checks.py::map_account_covers_scope`
to contain every account that appears in scope. That check is now
coverage, not exact equality: a scope account missing from the CSV is
still a failure, but the CSV may carry accounts beyond scope without
that counting as one. `115010`/`205010` are added to `map_account.csv`
under this relaxed rule - same tags as the other 3 pairs
(`account_role=clearing_pair`, `dq_flag`, `pair_id`,
`local_amount_expected=false`), a `notes` field stating they're outside
company 1000, and `status=unmapped` like every other clearing pair.

Reasoning for adding them now rather than waiting for a company
2000/2100/3000 ticket: leaving this pair fully undocumented would mean
whoever eventually loads those companies hits `local_amount=0` on a
pair already known and explained, with nothing in `map_account.csv`
pointing at the explanation - the exact silent-gap failure mode this
whole investigation exists to avoid.

`src/build_mapping.py`'s `CLEARING_PAIRS` constant now includes this
4th pair, injected by hand into `draft_map_account()`'s output since
`dim_account` (built from the company-1000 scope) never surfaces an
account with zero rows in that scope.

## What's explicitly not decided here

- **`4800`/`4810`**: also 100.00% defect rate, but 1 row each in the
  whole file - too thin to rule on with the same confidence as the 8
  accounts above. Left with Group B as unresolved, not folded into this
  ADR's decision.
- **Group B** (614 rows, 28 accounts): a separate, still-open question.
  See mission 14's Retro.
- Whether the 8 accounts' `target_account` should ever be populated (a
  real target CoA code, once one exists for clearing pairs generally) -
  unrelated to this ADR, which only rules on `local_amount`.

## Consequence: quality_gate.py needed no change

Checked before assuming a fix was needed: `local_amount_imbalance`
(`src/quality_gate.py`) flags a document when `SUM(local_amount) != 0`
across its lines. Since Group A's `local_amount` is always exactly
`0.0`, including or excluding those lines from that sum is
mathematically identical - adding zero never changes a sum. Confirmed
by query: 0 documents in the P01-P03 scope flagged by
`local_amount_imbalance` touch any Group A account. The gate was never
miscounting these lines as a bug; no code change was needed to "stop"
something that wasn't happening.