# Mission 12: Runbook + handover

- **Signal:** issue #12, blocked by #10 (closed).
- **Confidence:** high. Nothing here changes warehouse data or adds a
  new check; it documents what tickets 2 through 10 already built and
  pins the commands that reproduce it.
- **Type:** pure documentation + one dependency file. No SQL, no new
  table, no new check.
- **Decision:** act. Write `docs/runbook.md`, `requirements.txt`, and
  extend `README.md` to point at the diagram brief and the pattern
  notes. Time a fresh end-to-end run first so the runbook states real
  numbers, not estimates.

## Rules that apply

> "A fresh run by someone who hasn't seen the repo finishes a period in
> 20 minutes or less." (issue #12)

> "`docs/runbook.md`: how to run it, where it breaks, how to reload
> without inflating counts, where the mismatches land." (issue #12)

> "Re-loading the same period yields the same totals and row counts."
> (docs/requirements.md, definition of done)

## Exploration

Ran the full pipeline fresh against the current warehouse to time it and
confirm every command in the runbook is the real one, not a remembered
one:

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

- Wall time for the whole sequence: **2.0 seconds** (`user 5.24s, sys
  1.57s, 339% cpu` — DuckDB parallelizes across cores). Well inside the
  20-minute target; the real time cost for a newcomer is reading the
  runbook, not running it.
- Reran `load_fact.py 1000 2024 3` three times back to back:
  `SUM(local_amount)` held at `340,498,930.11` every time, row count
  13,521, document count 3,708 unchanged. Reload stability holds at the
  single-period level, not just across the P01/P02/P03 backfill mission
  10 already proved.
- `src/checks.py` only imports `duckdb` and the standard library
  (`csv`, `sys`, `pathlib`). Every notebook only imports `duckdb` (plus
  `csv` in mission 05's and mission 10's). No `pandas`/`pyarrow` import
  anywhere in `src/` or `notebooks/` — `read_parquet`/`read_csv_auto`
  run inside DuckDB itself. `requirements.txt` only needs to pin
  `duckdb`; `jupyter`/`nbconvert`/`ipykernel` are needed only to
  re-execute the notebooks, not to run a period.
- `python3 --version` is 3.9.6 in this environment. Confirmed during
  ticket 10 that `X | None` (PEP 604) fails at import time on 3.9 but
  bare `list[X]`/`dict[str, int]` (PEP 585) doesn't — worth a runbook
  line since it's the one Python-version trap this repo has actually
  hit.
- `README.md` already exists with a `## Docs` section listing
  `docs/architecture.md` (the diagram brief, `docs/architecture.png`
  itself doesn't exist yet — issue #1) and does not yet link
  `docs/design-patterns.md` ("the pattern notes"). Adding that link
  doesn't need to wait on #1.

## Desired outcomes

- `docs/runbook.md`, covering, in this order:
  1. Setup: `pip install -r requirements.txt`, `warehouse.duckdb` is
     gitignored and built fresh by the first script that runs.
  2. Run one period end to end: the 8-command sequence above,
     parameterized (`<company> <year> <period> [<period> ...]`), with
     the real timing from Exploration.
  3. Where it breaks: what `verify_rollback_safety` checks and what a
     `BLOCKED` exit means; what a blocking `dq_violations` row means
     for a document (never reaches `fact_gl_line`) versus a
     non-blocking one (loads and logs).
  4. Reload without inflating counts: `load_fact.py` deletes then
     re-inserts only the periods passed as arguments, one transaction;
     re-running with the same arguments never appends. No default
     period — a bare call fails with a usage message rather than
     guessing.
  5. Where mismatches land: `recon_mismatch` is built from `stg_gl`
     compared against the **close-eligible** subset of `fact_gl_line`
     (excludes `is_opening_balance` / `is_closing_entry` /
     `is_post_close` rows), not the full table — comparing against the
     full table only ever produces `missing_in_fact` (mission 08).
     Every row gets one bucket + one cause from the closed lists in
     `docs/definitions.md`.
  6. Reversal pairs: detected by convention (`reference` starts
     `REV-...`), reported against the **originating** period, so a
     pair crossing a period boundary doesn't net to zero in the period
     where it was posted — it still shows up as its own line in that
     period's mismatch table (mission 09's reversal-pairs section).
  7. Sign-off is split, every period: `reports/period_<period>.md`
     accepts the `stg_gl` vs `fact_gl_line` reconciliation but does not
     sign the reported `local_amount` total, because issue #13's
     broadcast-total defect is a whole-scope bug (confirmed in P01,
     P02, and P03 by mission 10), not a P01-only one.
  8. `python3 src/checks.py`: 56 regression checks, must stay green.
- `requirements.txt`: `duckdb==1.4.5`, pinned to what's actually
  installed and in use. A short comment marks `jupyter`, `nbconvert`,
  `ipykernel` as optional, only needed to re-execute `notebooks/*.ipynb`.
- `README.md`: add `docs/design-patterns.md` to the `## Docs` list
  ("pattern notes"); note that `docs/architecture.png` referenced by
  `docs/architecture.md` doesn't exist yet (issue #1), rather than
  linking a file that isn't there.

## Deterministic checks

- [x] `docs/runbook.md` exists and every command in it is copy-pasted
      from a real run in this mission's Exploration, not retyped from
      memory.
- [x] `requirements.txt` exists; `pip install -r requirements.txt` into
      a clean virtualenv, then `python3 src/checks.py`, passes 56/56.
      Verified twice, in two separate throwaway venvs.
- [x] `README.md` links `docs/design-patterns.md`.
- [x] A fresh clone + the runbook's own steps, timed, finishes under 20
      minutes. Actual stopwatch run in a clean venv: **1.96s wall time**
      for the full 8-command sequence, 56/56 checks passing.

## Non-deterministic checks

| Check | Who | How an agent verifies |
|---|---|---|
| the runbook reads clearly to someone who has never seen this repo, not just to someone who already knows the pipeline | you | you read it cold and flag any step that assumes context it hasn't given yet |

## Non-goals

- Not drawing `docs/architecture.png` — that's issue #1, ordered
  independently of this ticket.
- Not adding a new table, check, or SQL change. Pure documentation.
- Not changing anything about how a period is signed off; the runbook
  states mission 09/10's split sign-off rule, it doesn't revisit it.

## Human approvals

**Before build:**

- `requirements.txt` pins only `duckdb`, with `jupyter`/`nbconvert`/
  `ipykernel` called out as optional (notebook re-execution only), not
  required for running a period
- README gets one addition (link to `docs/design-patterns.md`), not a
  rewrite
- runbook does not fabricate a link to `docs/architecture.png` before
  issue #1 draws it

**Before the output is used (#1+):**

- you do a cold read of `docs/runbook.md` and confirm it holds up for
  someone with zero context, then comment "approved" on #12

## Retro

The pipeline itself needed nothing new. The only real work was reading
`src/*.py` and every mission doc closely enough to write down the
"where it breaks" and "where mismatches land" sections accurately,
instead of restating what each script's own docstring already says.

One thing worth a second look surfaced only from stopwatch-running the
full sequence three times in a row: `SUM(local_amount)` for P03 held at
`340,498,930.11` across every reload, not `.13` as an earlier mission
summary had it. Checked it wasn't a new instability — three consecutive
`load_fact.py 1000 2024 3` runs in this mission all agreed with each
other and with the currently committed `reports/period_2024-03.md`, so
`.13` was a stale figure from an earlier draft, not a live
non-determinism. Reload stability itself holds: same row count, same
document count, same total, every time.

`requirements.txt` ended up with exactly one pinned line
(`duckdb==1.4.5`) plus two commented-out optional ones. That's correct
for what this repo actually imports, not under-specified — confirmed by
grepping every `import` in `src/` and `notebooks/*.ipynb` rather than
assuming from the ecosystem what a "finance pipeline" usually needs.
