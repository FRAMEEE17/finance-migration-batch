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
- `map_account.csv` at repo root: `source_account, target_account, status`.
  Draft. `target_account` = the source's own `account_class` code (derived,
  not invented). `status` = `mapped` default; `unmapped` for null-class
  accounts; `deprecated` proposed (not decided) for suspense / clearing.
- Review report (comment on #3 + `docs/mapping-review.md`): the ~27 target
  groups with line count and net amount; the unmapped list with impact; the
  dirty-`fs_category` cases; the deprecated proposals.

## Deterministic checks

- [ ] `map_account.csv`: `source_account` is unique (rows == distinct).
- [ ] Every `gl_account` in scope appears exactly once in `map_account.csv`.
- [ ] `status` is in {mapped, unmapped, deprecated} for every row.
- [ ] `mapped` rows have a non-null `target_account`; `unmapped` rows have none.
- [ ] `dim_account` row count == distinct scope `gl_account`.
- [ ] `gl_account -> account_class` is 1:1 in scope. If false, "target =
      account_class" is impossible; escalate, do not proceed.
- [ ] The account set is `SELECT DISTINCT gl_account` unfiltered (no
      `is_fraud` / `is_anomaly` exclusion).

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

- you fill the 3 rulings, spot-check the 27 groups, comment "approved" on #3

## Retro

Filled after the mission closes.
