# Finance Migration + Reconciliation

Moving legacy GL into a new warehouse so finance can close a period and
explain every difference. Single context.

## Language

**Period**:
The pair `(fiscal_year, fiscal_period)` for one `company_code`. Not a
calendar-month string. Not `posting_date` either; a document's posting date
and its accounting period can disagree.
_Avoid_: month, date range

**stg_gl**:
The raw GL as loaded, as-is. No mapping, no dedup, no period logic. The
legacy side of every reconciliation in this project, since there is no
separate legacy-system extract.
_Avoid_: source table, legacy system

**fact_gl_line**:
One row per publishable GL line, after account mapping, the duplicate-grain
guard, DQ, and period-scope logic have run. The target side of every
reconciliation. A table is only called `fact_` once it is clean; dirty data
does not get a `fact_` name.
_Avoid_: target system, warehouse table (too vague, name the table)

**Publishable**:
A GL line that has passed DQ, has an `include_in_close = yes` doc type, is
not `is_post_close`, has a `mapped` account, and was loaded through the
idempotent path. Only publishable lines enter `fact_gl_line` close totals.

**Mismatch**:
A difference between `stg_gl` and `fact_gl_line` on one document or line. It
has two independent axes. A **bucket** is the symptom (missing, changed,
intentionally excluded). A **cause** is the reason. Exactly one of each.
Allowed values for both live only in `docs/definitions.md`. `unknown` is a
temporary state; it can't remain once a period report is signed.

**Bucket**:
Which symptom a mismatch shows (`missing_in_fact`, `missing_in_stg`,
`amount_changed`, `intentionally_excluded`). Answers where it shows up.
_Avoid_: type, category (too vague, say bucket or cause)

**Cause**:
Why a mismatch exists, drawn from the fixed list in `docs/definitions.md`
(`opening_balance`, `unmapped_account`, `duplicate_source`, `rounding`, and
so on). Answers why. A bucket without a cause is an unfinished investigation.

**Duplicate grain**:
The same `company_code + document_id + line_number + fiscal_year +
fiscal_period` appearing more than once. A blocking DQ violation
(`duplicate_source`). There is no "keep the latest row" step, because
nothing in the source says which copy is latest. Not the same as a reversal
pair (different `document_id`s), a post-close document (same row with a
flag), or a late-arrival document (a different period). These four never go
through one dedup function.
_Avoid_: dedup (implies an automatic pick, which this project does not do)

**Reversal pair**:
A document detected as reversing another one, by textual convention
(`reference` = `REV-<uuid>`, `header_text` = "Reversal of `<document_id>`").
There is no status column for this. Both sides of the pair are kept. Neither
is deleted. The two sides have different `document_id`s, so this is not a
duplicate grain.
_Avoid_: cancelled document (no `is_cancelled` column exists to justify that word)

**Post-close document**:
A document with `is_post_close = true`, posted after the period's close
ritual. Excluded from in-period close totals, reported in its own bucket,
never deleted. Same period and same grain as any other row, just flagged.
_Avoid_: cancelled, invalid (it is neither, it is just late)

**Late-arrival document**:
A row belonging to a period outside current close scope, such as the FY2025
P02 rows. Kept in `stg_gl`, left out of the report. This is a scope
question, not a per-row flag like post-close.

**map_fanout**:
A blocking error where `map_account.source_account` has more than one row.
Many sources may map to one target. One source must never map to many.
Checked before every period load.

**Flagged row** (`is_fraud`, `is_anomaly`):
A source-planted defect. It is reconciliation *content*. It is not filtered
before processing. If it causes a difference, that difference shows up in
the mismatch report.
_Avoid_: bad data, dirty row (implies "clean by deleting", the opposite of the rule here)

**Unmapped account**:
A `gl_account` absent from `map_account.csv`, present with
`status='unmapped'`, or present with `status='deprecated'` and no
`target_account`. Not the same as `status='catch_all'`, which is a
resolved classification, not an open gap (see Catch-all account below). A
target code for this gap is set by a human in the approved mapping file,
never assigned automatically. `unmapped` says nothing about whether the
account is still live in the source; see Account disposition vs account
usage below.

**Account disposition vs account usage**:
Two different questions about one `gl_account`, kept in two different
columns of `map_account.csv` on purpose. `status` (`mapped` / `unmapped` /
`deprecated` / `catch_all`) answers "does this have a place in the target
chart of accounts." `source_usage` (`live` / `retired`) answers "is the
source system still posting to it." An account can be `deprecated` and
`live` at the same time (we are retiring the code, but it is still being
posted to today, so it needs a target for the live postings to land on).
Conflating the two into one status value hides exactly that case.
_Avoid_: reading `deprecated` as "no longer used." It means "not carried
forward," which is a design decision, not an observation about activity.

**Catch-all account**:
A `gl_account` that is a migration parking code, not a real business
account: one code absorbing postings with no real destination, visible as
many unrelated `account_description` values on the same code, spanning
companies and periods beyond the current migration scope. `status=catch_all`
(ADR-0005). Always flagged (`fs_category_flag=true`), never folded into an
`account_class`'s vote, still keeps a `target_account` (its own code, a
live account still needs somewhere for postings to land, not a class).
_Avoid_: "dummy account" (reads as "no real value moves through it," which
is false here) and treating it as a synonym for `unmapped` or `deprecated`.

**Clearing pair**:
Two `gl_account` codes that only make sense read together: one posts
debit-only, the other credit-only, and their amounts move in tandem. Linked
by `pair_id` in `map_account.csv`. A pair present with only one side
mapped, or with each side on a different `status`, is a validation error.

**Balance validation vs close totals**:
Two different checks over the same document, using two different columns.
Validation (`debit_amount − credit_amount = 0`) decides if a document is
publishable. Close totals (`sum(local_amount)`) are what gets reported. They
can disagree (see `local_amount_imbalance`) without either being wrong about
its own question.

**local_amount_imbalance**:
A finding on a document that balances on `debit_amount − credit_amount` but
whose `local_amount` does not net to zero. Reported, never a publish
blocker. Cause varies by magnitude, not always rounding: a gap of a few
cents is currency-conversion rounding, but a gap in the thousands or
millions has shown up from a source-data defect (a document-level total
broadcast onto every line instead of a real per-line amount, see
`docs/period-close-notes/2024-01-local-amount-defect.md`). Check the size
of the gap before assuming which one it is.

**Closed period**:
A period whose `reports/period_YYYY-PP.md` a human has accepted. It is not a
database state, a green pipeline, or a loaded table.
_Avoid_: done, loaded, green

**Intended fix**:
A difference the pipeline creates on purpose: excluding period-boundary
documents, excluding post-close, blocking unbalanced documents. It is
written into the rules before it appears in a report, and it still shows up
in the report as a named cause.

**Period-boundary document**:
An `OPENING_BALANCE` (brought-forward) or `CL` (closing) document. Excluded
from in-period close totals by design. This is an intended fix, not a
mismatch to investigate.

**unmapped_doc_type**:
The status of a document whose type is outside the 12-row doc_type catalog.
Not counted in the close, and never guessed into revenue or expense.

**Idempotent period load**:
A load that replaces the whole period and never appends. Re-running with
unchanged mapping gives identical row counts and totals.
_Avoid_: incremental load, upsert, append

**transaction_amount**:
The document-currency amount before conversion. Never summed at period level
for anything.
_Avoid_: amount (always say which one)
