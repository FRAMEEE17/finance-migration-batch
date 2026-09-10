# Add `catch_all` to the map_account status enum

**Status:** accepted

`map_account.status` was a closed set of three values: `mapped`, `unmapped`,
`deprecated`. Two gl_account codes, `199999` and `999999`, don't fit any of
them. Each carries a dozen or more unrelated `account_description` values
(one line reads "Legacy Suspense (migrated)", another on the same code
reads "Land," another "Service Revenue 22") and appears across all 4
companies and all 13 periods in the source, not just the current migration
scope. This is not one account behaving inconsistently. It's a migration
catch-all code absorbing postings that had nowhere else to go, the pattern
SAP's own docs describe for dummy/default objects during migration.

None of the three existing values describe it honestly. `deprecated` means
"we are not carrying this source code into the target CoA," which implies
someone decided to retire a real account. `unmapped` means "we haven't
decided a target yet," which implies the account itself is a normal,
undecided case. Neither is true here: these codes are still live (real
debit/credit activity in every company and period observed) and they were
never one coherent account with a job.

## Decision

Add a fourth status: `catch_all`. A `gl_account` gets this status when it is
a migration parking code absorbing unrelated postings across scope
boundaries (companies, periods), not a real business account. Rules:

- `fs_category_flag` is forced `true` for every `catch_all` row in
  `dim_account`, regardless of whether the account happens to look
  internally consistent within the current scope window. The
  inconsistency this flag exists to signal is often only visible outside
  the current scope, and the flag must not depend on the scope being wide
  enough to catch it.
- `catch_all` rows are excluded from any account_class-level majority-vote
  or dirty-class computation (the `financial_statement_category` split
  reported per `account_class`). They would otherwise dominate or distort a
  real class's vote by sheer volume without being a real member of it.
- `catch_all` still gets a `target_account`. It is not a synonym for
  "drop this data." A catch-all code with live activity keeps its own
  source code as its target (see the account_role note in
  `docs/definitions.md`), reported on its own line, not folded into a
  class it does not really belong to.
- Two catch-all codes covering different `financial_statement_category`
  values (one reads as `asset`, the other as `suspense` in the current
  scope) get separate reporting lines. Nothing forces them into the same
  bucket just because they share a status.

## Explicitly not decided here

- Whether some other `gl_account` found in a future scope also deserves
  `catch_all`. This decision covers `199999` and `999999`, identified by a
  specific cross-scope query, not a general auto-detection rule.
- `pending_pair_map` (the working state for the 3 clearing-pair accounts
  under review in the same ticket) does not become a fifth status. It is a
  temporary process-layer condition on an `unmapped` row, not a permanent
  chart-of-accounts disposition, and does not belong in this enum. See
  `docs/definitions.md` for how it's represented instead (`account_role` +
  `dq_flag` + `pair_id`, not `status`).
