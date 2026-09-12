# Mission 17: unmapped_account catches accounts absent from map_account.csv

- **Signal:** issue #17, no blocker.
- **Confidence:** high. One query in `quality_gate.py` to change; the
  fact-finding (does this affect real data today) is answered before
  any code changes.
- **Type:** bug fix - `quality_gate.py`'s implementation doesn't match
  `docs/definitions.md`'s own documented definition.
- **Decision:** act, narrowly. Per your ruling: catch accounts
  genuinely absent from `map_account.csv` into `dq_violations`. Don't
  touch `build_dim_account`'s majority-vote logic or the 115/205
  clearing-pair family in this same change.

## Rules that apply

> "docs/definitions.md's unmapped_account means a gl_account not
> present in map_account.csv, present with status='unmapped', or
> present with status='deprecated' and no target_account."
> (docs/definitions.md:200, already-existing rule this mission makes
> the code match)

> "ขอบเขตให้แคบ: บัญชีที่โผล่ในสเตจแต่ไม่มีแถวใน map_account.csv ต้องเข้า
> dq_violations. อย่าไปรื้อ majority vote หรือชุด 115/205 ทั้งก้อนในใบเดียว."
> (your ruling on this ticket)

## Exploration

Checked before writing any code, per issue #17's own first "Done when"
line: does this gap affect the real P01-P03 scope today?

```
accounts in stg_gl scope: 505
accounts in map_account.csv: 507
in stg_gl but missing from map_account.csv: 0
```

Zero. `build_mapping.py` derives `map_account.csv` directly from the
distinct accounts in scope, so every account that exists in the real
data structurally always gets a row - confirms this mission's earlier
finding (mission 18's retro) that the gap is latent for real data, not
active. This fix changes zero real `dq_violations` rows, zero real
report figures, zero `src/checks.py` anchors - safe to verify by
running the full real pipeline unchanged before and after.

The fix only has a visible effect on `tests/fixtures/journal_entries_ci.parquet`'s
`CI-DOC-UNMAPPED-001` (account `999888`, deliberately absent from the
real map file) - `tests/ci_checks.py`'s
`unmapped_account_loads_without_flag_known_gap` currently pins the gap
as-is; this mission turns it from a documented gap into a real pass.

## Desired outcomes

- `quality_gate.py`'s `unmapped_account` query catches both cases in
  one pass: a `gl_account` with zero rows in `map_account`, and a
  `gl_account` present but `status='unmapped'` or
  `status='deprecated'` with no target - a `LEFT JOIN` replacing the
  current IN-list-from-a-subquery, not two separate checks.
- Detail message distinguishes which case fired ("has no row in
  map_account.csv" vs "is unmapped"), so a reader of `dq_violations`
  doesn't have to guess.
- `tests/ci_checks.py`'s check renamed and reassert: the fixture's
  absent account now gets flagged for real.
- Real pipeline re-verified unchanged: same `checks.py` 70/70, same
  report figures, same `dq_violations` counts for P01-P03.

## Deterministic checks

- [x] Real dataset: `dq_violations` counts for `unmapped_account`
      unchanged for P01/P02/P03 - 15/12/14 both before and after,
      reconfirmed by rerunning `load_fact.py` post-fix, not assumed.
- [x] `src/checks.py` still 70/70 after the change. Reports
      byte-identical (`git status --short reports/` clean).
- [x] CI fixture: `CI-DOC-UNMAPPED-001`'s account `999888` is now
      logged non-blocking (1 row), not silently absent.
- [x] `tests/ci_checks.py` passes end to end, 8/8, with the renamed
      `unmapped_account_logged_not_excluded` asserting the fixed
      behavior instead of pinning the old gap. Confirmed on real
      GitHub Actions infrastructure, not just locally: run
      [34719092505](https://github.com/FRAMEEE17/finance-migration-batch/actions/runs/34719092505),
      `unmapped_account logged=1 (want >0)`, `8/8 passed`.
- [x] `build_dim_account`'s majority-vote query and the 115/205
      clearing-pair handling are byte-identical - `git diff --stat`
      shows only `src/quality_gate.py` touched, `src/build_mapping.py`
      untouched.

## Non-goals

- Not touching the majority-vote / dirty-class logic in
  `build_mapping.py`.
- Not touching the 115/205 clearing-pair family or ADR-0007.
- Not starting Airflow (mission 18's own deferred item) - explicitly
  parked until this gate gap closes first, per your ordering.

## Human approvals

**Before build:** none needed - your message locked the scope
completely (which case to catch, which two things not to touch).

**Before the output is used:** you confirm the real-data no-op claim
holds, comment "approved" on #17.

## Retro

The fact-check came first and settled the risk before any code moved:
zero real accounts are missing from `map_account.csv` today, so this
fix could only ever be a no-op on the real dataset or a real
improvement on future data - never a regression. That made the rest of
the mission low-stakes in a way most quality-gate changes in this
project haven't been (compare mission 06's local_amount finding, which
changed nothing but *discovered* a lot).

The one-line summary of the fix: `unmapped_account` used to build an
IN-list from accounts already inside `map_account.csv` and then ask
"which `stg_gl` rows match that list" - a query that can only ever see
accounts the file already knows about. Replacing it with a `LEFT JOIN`
flips the question to "which `stg_gl` rows have no match at all," which
is the actual definition `docs/definitions.md` already had written
down. The bug wasn't in the SQL being wrong, it was in the SQL
answering a narrower question than the one it was named after.

`tests/ci_checks.py`'s known-gap check flipping from pass to fail the
moment the fix landed, then getting rewritten to assert the new
behavior, is exactly what mission 18's retro predicted this would look
like - a deliberate, visible change to a pinned check, not a silent
one. Confirms the pin was worth adding even for a gap nobody was
rushing to fix.

Scope stayed exactly as locked: `build_mapping.py`'s majority-vote
logic and the 115/205 clearing-pair family never got touched, verified
by `git diff --stat` rather than by intention alone.
