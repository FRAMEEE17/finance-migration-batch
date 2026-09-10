# Mission 01: Target chart of accounts + account mapping

- **Signal:** issue #3, part of the 12-ticket plan from grilling Q1-Q8 / G1-G3
- **Confidence:** high. Planned, dependency-ordered, written AC, grounded in `docs/definitions.md`.
- **Type:** request with an embedded risk. The risk: #3 is the human-judgement
  gate. A wrong mapping makes every downstream number (#6, #8, #9) wrong, and
  it is the one ticket where the model must not decide.
- **Decision:** act, bounded. Act = produce a reviewable draft, not decide the
  mapping. Build `dim_account` (mechanical rollup), draft `map_account.csv`
  (proposals only), a review report. Then stop for human approval before
  anything reconciles.

## Rules that apply

> "**Mapping:** no real target chart of accounts exists yet. First pass
> derives one from the source `account_class` hierarchy (~27 rows). A human
> approves `map_account.csv` (`source_account, target_account, status`) before
> any reconcile run. `source_account` must be unique; duplicates are a
> blocking `map_fanout` error, checked every load. Accounts with no target are
> marked `unmapped`. Target account codes are never guessed. They come only
> from the approved mapping file." (docs/business-rules.md)

> "`status` is one of `mapped`, `unmapped`, `deprecated`. A human approves
> this file. No target code is invented." (docs/definitions.md)

> "Many sources mapping to one target is allowed... One source mapping to
> many targets is the fan-out case this guards against." (docs/definitions.md, map_fanout section)

> "Reconciling differences or changing a business rule is careful work. Slow
> down for it." (docs/business-rules.md, working rules)

> ADR-0003: is_fraud / is_anomaly rows flow through, never filtered. The dirty
> `financial_statement_category` values are likely planted; surface them, do
> not clean them.

## Desired outcomes

- `dim_account` table in `warehouse.duckdb`: one row per `gl_account` in scope
  (company 1000, FY2024 P01-P03), with `account_sub_class`, `account_class`,
  `account_class_name`, `account_description`, and one proposed `fs_category`
  (majority vote per account, flagged where the source disagrees with itself).
- `map_account.csv` at repo root: `source_account, target_account, status,
  source_usage, account_role, dq_flag, pair_id, notes`. Draft. `target_account`
  = the source's own `account_class` code for an ordinary rollup account,
  or the account's own code for a clearing/clearing_pair/catch_all account
  (derived, not invented, either way). `status` = `mapped` default;
  `unmapped` for the null-class / clearing-pair accounts; `catch_all` for
  the two hand-ruled migration parking codes (ADR-0005). `deprecated` ended
  up unused this round — every suspense/clearing candidate turned out to be
  either a real live clearing account or a catch-all code, not something
  actually being retired from the target CoA.
- Review report (comment on #3 + `docs/mapping-review.md`): the ~27 target
  groups, the clearing accounts, the clearing pairs (with a filed dq_flag),
  the catch-all accounts, and the dirty-`fs_category` classes.

## Deterministic checks

- [x] `map_account.csv`: `source_account` is unique (rows == distinct).
- [x] Every `gl_account` in scope appears exactly once in `map_account.csv`.
- [x] `status` is in {mapped, unmapped, deprecated, catch_all} for every row
      (catch_all added by ADR-0005 mid-mission).
- [x] `mapped`/`catch_all` rows have a non-null `target_account`; `unmapped`
      rows have none; `deprecated` only needs one when `source_usage=live`.
- [x] `dim_account` row count == distinct scope `gl_account`.
- [x] `gl_account -> account_class` is 1:1 in scope. If false, "target =
      account_class" is impossible; escalate, do not proceed.
- [x] The account set is `SELECT DISTINCT gl_account` unfiltered (no
      `is_fraud` / `is_anomaly` exclusion).
- [x] `catch_all` accounts are always `fs_category_flag=true` in `dim_account`.
- [x] Every `clearing_pair` row has a complete, status-matched partner.

## Non-deterministic checks

| Check | Who | How an agent verifies |
|---|---|---|
| the ~27 target groups make accounting sense | you | LLM pre-screens: flag any `account_class` whose prefix (A/L/E/R/X) disagrees with its majority `fs_category`; agent confirms each flag has a proposed resolution and a "needs ruling" marker in the report |
| majority-vote `fs_category` per account is right | you (~6 classes) | LLM re-derives the vote from `stg_gl`, diffs against `dim_account`, no cherry-picking |
| suspense / clearing: carry forward or `deprecated` | you (business call) | agent confirms the CSV leaves these as a marked proposal, not a silent decision |
| the 6 null-class accounts are safe to drop | you | LLM surfaces their line count and net (~$0) for a materiality call |

## Non-goals

- Not inventing numeric target codes (1000 / 2000 / ...). Target = source
  `account_class`. A numeric scheme is a later, human-initiated call.
- No reconciliation. #3 stops at the approved mapping.
- Companies 2000 / 2100 / 3000, periods outside FY2024 P01-P03. Out.
- Not editing `stg_gl` to fix the dirty `fs_category` (raw, immutable).
- Not dropping any `gl_account` for a fraud / anomaly flag.
- Not auto-resolving inconsistent-category accounts. Surface, do not decide.
- `dim_account` is not SCD Type 2 (no history; one current row per account).

## Human approvals

**Before build:**

- `target_account` = source `account_class` code (e.g. `A.A`), not a new
  numeric scheme
- `dim_account` keyed on `gl_account` (505 rows), `account_class` as an attribute
- inconsistent `fs_category` -> majority vote per account, flagged
- `map_account.csv` at repo root, committed to git
- suspense / clearing enter the CSV as `status=deprecated` proposal, awaiting
  your ruling
- run the read-only `gl_account -> account_class` 1:1 verification (SELECT
  only, no state change)

**Before the output is used (#4+):**

- [x] you fill the 3 rulings, spot-check the 27 groups, comment "approved" on #3

The 3 rulings turned out to need a full grilling pass each, not a quick
yes/no: the 5 "clean" suspense/clearing accounts and the 6 "immaterial"
unmapped accounts both failed their first-pass read once checked against
the full dataset (all companies, all periods) instead of just the current
scope. See Retro.

## Retro

The one durable rule this mission adds: **a mapping-review report must
check the full dataset before calling anything immaterial or inactive, not
just the current scope.** Twice this mission, a scope-limited query gave a
plausible-looking wrong answer:

- The 5 "clean" suspense/clearing accounts looked dormant enough to
  `deprecated` from a single description and a coherent name. Checked
  against the full 4-company, 13-period dataset, all 5 are still live with
  material balances. `deprecated` almost got attached to real, active
  accounts.
- The 6 "immaterial" unmapped accounts showed `local_amount = 0` net and
  gross. Checked against `debit_amount`/`credit_amount` instead, all six
  carry real money (millions) as three debit-only/credit-only pairs. The
  original report's "safe to drop, $0 net" framing was misleading because
  it only ever looked at one column.

Added to `docs/definitions.md`: `status` (target-CoA disposition) and
`source_usage` (is the source system still posting to it) are two different
questions and must never share one column, on pain of exactly the
`deprecated`-a-live-account mistake above. `catch_all` (ADR-0005) is scoped
narrowly on purpose — it names the specific pattern of `199999`/`999999`,
not a general "weird account" bucket.
