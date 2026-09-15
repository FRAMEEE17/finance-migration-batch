# Mission 21: Airflow recovery, run evidence, and final period-close gate

- **Signal:** proposed issue #21, follows mission 20. Combines the two
  highest-priority production gaps: a real close gate at the end of the
  DAG, and proof the pipeline can fail and recover without losing or
  mixing data.
- **Confidence:** high on the existing pipeline and where the gate has to
  sit. Two things need a human call before build: the alert destination,
  and a rounding discrepancy in the existing 20% unknown-mismatch rule.
- **Type:** request.
- **Decision:** act. A green DAG Run should mean the requested period
  passed real close checks, with the inputs it ran against traceable, and
  a demonstrated recovery from a mid-run failure.

## Rules that apply

From `CLAUDE.md`:

> - Work one ticket at a time.
> - No SQL change without a mismatch report first.
> - Never fix totals by editing target amounts.
> - SQL is the reconcile engine, not Pandas.
> - A green test is not a closed period until `reports/period_YYYY-PP.md`
>   exists and `period_signoff` carries that period's status (ADR-0008:
>   the report is a working paper, `period_signoff` is the
>   machine-readable close state).
> - **Period load:** replacing a period replaces the **whole** period,
>   never append. Re-running with unchanged mapping must yield the same
>   totals and row counts.

From `docs/definitions.md`:

> Reconciliation compares `stg_gl` against `fact_gl_line` per period and
> per account. Every row `stg_gl` has that `fact_gl_line` does not, and
> every changed amount, must have a named cause.

> `local_amount` not netting to zero on an otherwise-balanced document is
> a separate finding. Flag `local_amount_imbalance`, don't block
> publication on it.

> If `unknown` mismatches exceed 20% of the period's total mismatch
> count, the period report cannot be signed.

## Exploration

No notebook for this one - this is orchestration and evidence, not a
reconciliation question. Read the DAG, `checks.py`, the report builder,
the analyst view, and the runbook directly instead.

`dags/gl_period_close.py` has seven tasks today:
`load_stg → load_fact → reconcile_account → reconcile_reversals →
reconcile_mismatch → build_period_report → build_analyst_view`.
`schedule=None`, `max_active_runs=1`, one retry. No failure callback, no
record of which source file or mapping version a run actually consumed,
and nothing enforces that the DAG's last task means "this period is
closeable." `quality_gate.run_gate()` already runs inside
`load_fact.load_period()`, but that's a row-level ingestion gate, not a
period-level close gate.

`src/checks.py`'s 72 checks can't run unchanged as a production gate.
Several are pinned to the real dataset (`P01_FACT_ANCHOR`, known mismatch
counts) or loop over `BACKFILL_PERIODS` - they're regression tests for
this dataset, not a general-purpose "is this period ready" check. A real
gate has to be period-scoped and callable for whatever period the DAG run
asked for, not just periods 01 through 03.

Two things need resolving before this gets built, not just before it
ships:

- `docs/definitions.md` says unknown mismatches must not **exceed** 20%.
  The code checks `< 20.0` after rounding the percentage to one decimal.
  Those aren't the same rule at the boundary - a period at exactly 20%
  passes today's code but should fail by the doc's own wording.
- The three close artifacts don't agree on vocabulary at that boundary
  either: the working paper says `Reconciliation: accepted`, the
  controller pack says `rejected`, `period_signoff` says `blocked`. The
  gate has to read the machine state (`period_signoff`), not re-derive a
  decision from report text.

## Desired outcomes

- `dags/gl_period_close.py` gets one new task, `period_close_gate`, after
  `build_analyst_view`. It's the DAG's actual last task and its only
  leaf.
- New `src/period_close_gate.py` with `run_period_close_gate(con,
  company_code, fiscal_year, fiscal_period)`. Checks the requested
  period's reconciliation integrity, mismatch coverage, signoff row, and
  the three close artifacts, and raises on failure. It doesn't call
  `checks.main()` and doesn't rebuild anything - it reads what the
  earlier tasks already produced.
- `src/checks.py` gets regression coverage for the gate's pass and fail
  cases, using isolated fixture data, not the real dataset - the gate has
  to work for a period other than 01-03.
- New `src/airflow_run_evidence.py` and a `reports/airflow_runs/`
  directory recording, per attempt: DAG run id, task, period requested,
  outcome, the source file and mapping file's content hash (SHA-256),
  and the gate's result. A recovered run can't silently mix staging built
  from one source version with a mapping from a different version - a
  changed input means a fresh full run, not a partial retry.
- A failure notification (destination TBD, see approvals below) fires
  once retries are exhausted on any task, including the new gate. It
  carries the run id, task, attempt, period, the exception, and a link to
  the recorded evidence.
- A real controlled-failure demo: inject a reversible failure into
  `reconcile_mismatch` on an already-closed period, let it fail through
  its retry, confirm the alert fires, clear the fault, clear/rerun the
  task and everything downstream, and diff the recovered tables and
  artifacts against a baseline taken before the failure.
- `docs/runbook.md` documents the new gate, the alert, where the evidence
  lives, and the recovery sequence.

## Deterministic checks

- [ ] DAG has exactly 8 tasks in order; `period_close_gate` is the sole
      leaf, directly after `build_analyst_view`.
- [ ] `schedule=None`, `max_active_runs=1`, `retries=1`, required
      company/year/period params all still set.
- [ ] Gate checks are period-scoped: an isolated fixture for a period
      outside 01-03 passes on valid data; a planted defect in one period
      doesn't affect another period's gate result.
- [ ] Missing evidence fails loudly: no `period_signoff` row, a duplicate
      row, or a missing report/controller-pack/exceptions file for the
      requested period all fail the gate with a named reason.
- [ ] Gate recomputes the account-level reconciliation independently
      (not by trusting `recon_period_summary` blindly) and compares.
- [ ] Gate recomputes mismatch coverage against the fact subset and
      confirms every material gap has a supported cause.
- [ ] Unknown-mismatch threshold: test 0%, under 20%, exactly 20%, over
      20%, and a value that rounds to 20.0 - confirm gate, report, and
      signoff agree on the approved rule (see approvals).
- [ ] `fact_gl_line_ready` only exposes rows for periods the gate
      actually accepted.
- [ ] A planted invalid state (e.g. signoff row missing) fails the DAG
      run through the gate task, not silently.
- [ ] Recorded source/mapping hashes match the bytes actually consumed;
      a changed-input rerun is rejected, not merged with stale evidence.
- [ ] A real triggered failure (not a unit test) exhausts the retry and
      the notification actually delivers to the test destination with
      run id, task, period, and exception present.
- [ ] Controlled recovery: baseline captured before the fault, fault
      injected into `reconcile_mismatch` after its own rebuild completes,
      retry exhausts, alert delivers, fault removed, task and downstream
      cleared and rerun, gate passes.
- [ ] Recovered `fact_gl_line`, `recon_period_summary`, `recon_mismatch`,
      `fact_gl_line_ready`, and the three report artifacts match the
      baseline exactly (row counts, classifications, monetary totals to
      the existing 0.01 tolerance) - `generated_at` timestamps excluded.
- [ ] All 72 existing checks still pass; new gate checks pass; no
      failure-injection code path runs during normal execution.

## Non-deterministic checks

| Check | Who | How an agent verifies |
|---|---|---|
| The alert gives an operator enough to act on without opening the DAG first | human | Trigger the controlled failure, read the delivered notification cold |
| Recovery is followable from the runbook alone | human | Follow only `docs/runbook.md`'s new section, confirm it reaches a passing gate |
| The three close artifacts still read consistently at the 20% boundary | human | Generate a period at exactly the threshold, read all three side by side |

## Non-goals

- No DQ framework adoption, no change to existing DQ check
  classifications - that's a separate, later ticket.
- No engine swap, no DuckDB replacement.
- Doesn't touch issue #13 (`local_amount` on high-line documents).
- The gate is not `checks.py`'s full 72-check suite run as a task - it's
  a narrower, period-scoped set built for this.
- No new schedule, no DAG split, no concurrency increase.
- No dashboard, no PDF export, no accounting-system signoff. This is
  still an evidence trail, not a replacement for finance's own approval.

## Human approvals

**Before build:**

- Where does the failure notification actually go? (email, Slack
  webhook, something else - needs a real destination to test against)
- Resolve the 20%-boundary rule: is exactly 20% a pass or a fail? The
  doc says "exceed 20%" (implying 20% itself passes); the code checks
  `< 20.0` after rounding (implying exactly 20% could pass or fail
  depending on rounding direction). Pick one, write it into
  `docs/definitions.md`, then match the gate/report/signoff to it.
- Which period and which copy of the warehouse does the controlled-failure
  demo run against? Needs to be isolated from the real `warehouse.duckdb`
  so a deliberately broken run can't touch real signed-off data.

**Before the output is used:**

- Review the delivered alert, the recovery evidence, the input hashes,
  and the baseline-vs-recovered diff.
- Confirm the requested period's `period_signoff` and all three artifacts
  agree before treating any demo period as a real reference case.

## Retro

Filled after the mission closes.
