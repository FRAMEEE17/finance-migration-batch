# Runbook

How to run one period end to end, what breaks and what it means, and how
to reload without inflating counts. Written for someone who has never
seen this repo.

## Setup

```
pip install -r requirements.txt
```

`warehouse.duckdb` is gitignored. It doesn't need to exist first — the
first script below creates it.

## Run one period end to end

```
python3 src/load_stg.py
python3 src/load_fact.py <company_code> <fiscal_year> <fiscal_period> [<fiscal_period> ...]
python3 src/reconcile_account.py
python3 src/reconcile_mismatch.py
python3 src/build_period_report.py <company_code> <fiscal_year> <fiscal_period>
python3 src/checks.py
```

For this repo's current scope (company `1000`, fiscal year `2024`,
periods `01`-`03`):

```
python3 src/load_stg.py
python3 src/load_fact.py 1000 2024 1 2 3
python3 src/reconcile_account.py
python3 src/reconcile_mismatch.py
python3 src/build_period_report.py 1000 2024 1
python3 src/build_period_report.py 1000 2024 2
python3 src/build_period_report.py 1000 2024 3
python3 src/checks.py
```

This whole sequence takes about 2 seconds on a normal laptop (DuckDB
runs each query across every core it can find). The 20-minute budget in
issue #12 is for reading this file and understanding what you're
looking at, not for the commands to finish.

`src/checks.py` should end with `56/56 passed`. If it doesn't, read the
failing check's own name and detail line before touching any SQL — each
one states what it measured, not just pass/fail.

## Where it breaks

**A missing or wrong argument.** `load_fact.py` and
`build_period_report.py` both fail with a usage message and exit code 1
if you call them with nothing, or the wrong count of arguments. Neither
one has a default period. Loading a period is a decision you make on
the command line, not something the script guesses for you.

**`BLOCKED: rollback safety check failed`.** `load_fact.py` runs
`verify_rollback_safety()` before every real load: it opens a
transaction, deletes the period's rows, deliberately queries a table
that doesn't exist, and confirms the rollback put the row count back to
what it was. If that check itself fails, the script exits before
touching real data — something is wrong with the database file or the
DuckDB install, not with the source data.

**A blocking `dq_violations` row.** `run_gate()` in `quality_gate.py`
runs five checks: `unbalanced_document`, `duplicate_source`,
`map_fanout`, `null_key_column`, `unmapped_doc_type`. Any row that
trips one of these never reaches `fact_gl_line` — it's logged in
`dq_violations` with `blocking = true` instead. Three more checks
(`local_amount_imbalance`, `unmapped_account`, `catch_all_account`) are
non-blocking: they get logged too, but the row still loads normally.
`dq_violations` is the first place to look when a period's row count
looks smaller than `stg_gl`'s for the same scope.

## Reload without inflating counts

`load_fact.py` deletes and re-inserts only the periods you pass on the
command line, in one transaction, every run. Calling it again with the
same arguments gives the same row count, document count, and
`SUM(local_amount)` — it never appends. `reconcile_account.py` and
`reconcile_mismatch.py` follow the same rule at the summary-table level:
call them with no arguments and they rebuild every period currently in
`fact_gl_line`; call them with a list of `(company, year, period)`
triples and they delete and rewrite only those periods, leaving every
other period's already-built rows untouched. Neither script issues a
bare `DELETE`/`CREATE OR REPLACE TABLE` against the whole table — an
earlier draft of both did, and it would have silently wiped every
period except the one being reloaded (see `docs/missions/10-backfill-2024-02-03.md`).

## Where mismatches land

`recon_mismatch` compares `stg_gl` against the **close-eligible** subset
of `fact_gl_line` — the rows that are not flagged
`is_opening_balance`, `is_closing_entry`, or `is_post_close`. Comparing
against the full `fact_gl_line` table instead only ever produces the
`missing_in_fact` bucket, because those three flags load a row and flag
it rather than excluding it from the table. Every row in
`recon_mismatch` carries exactly one bucket (the symptom) and one cause
(the reason), both from the closed lists in `docs/definitions.md`. A
period's `unknown` cause rate has to stay under 20% or the report can't
be signed.

Reversal pairs (`reference` starting `REV-...`, linked to the original
by document ID) are reported against the period the **original**
document posted in, not the reversal's period. A pair that crosses a
period boundary doesn't net to zero and disappear in the original
period — it still shows up there as its own line, because the
reversal itself hasn't happened yet as far as that period is concerned.

## Sign-off is split

Every `reports/period_<year>-<period>.md` separates two different
claims:

- the `stg_gl` vs `fact_gl_line` reconciliation — signed, once the
  gap is 0.00 and every account matches
- the reported `local_amount` total — **not signed**, because a set of
  documents has `local_amount` broadcasting a document's grand total
  across every debit line instead of a real per-line amount (issue
  #13). Both sides of the reconciliation inherit the same broken
  number, so a clean reconciliation doesn't mean the total is right.

This isn't a P01-only caveat. Mission 10 confirmed the same defect
shape in P02 and P03, growing each period (20 documents / $97.1M in
P01, 27 / $104.1M in P02, 36 / $340.5M in P03). Until issue #13 fixes
the source, the number to use for period judgment is the debit/credit
gap, not `local_amount`.

## One Python-version trap

This repo runs on Python 3.9. `X | None` type-hint syntax (PEP 604)
fails at import time here — use `typing.Optional[X]` instead. Bare
generic hints like `list[int]` or `dict[str, int]` (PEP 585, no union)
work fine on 3.9; only the `|` union operator needs `typing`. This bit
`src/reconcile_account.py` and `src/reconcile_mismatch.py` during
mission 10 before it was caught.

## Notebooks

`notebooks/*.ipynb` hold the Exploration behind each mission — real,
executed queries, not narrated ones. They're not part of running a
period; open them directly to read the output already in them. To
re-execute one:

```
pip install nbconvert ipykernel
jupyter nbconvert --to notebook --execute --inplace notebooks/<name>.ipynb --ExecutePreprocessor.kernel_name=python3
```
