# Mission 20: Airflow DAG for the existing period-close pipeline

- **Signal:** issue #20, no blocker.
- **Confidence:** high on shape. A full grilling round settled operator
  choice, DAG count, trigger model, and gate placement before any code
  gets written, and one of those answers got corrected after actually
  reading the source, not left as a guess.
- **Type:** build, orchestration only. No reconciliation logic changes.
- **Decision:** act. One DAG, `@task`/PythonOperator calling the
  pipeline's existing functions, manual trigger, checks as the last
  task, `max_active_runs=1`.

## Rules that apply

> "ยังไม่ทำ Airflow ถัดไปทำ #17 ก่อน" / "อย่ากระโดดไป Airflow ตอนนี้"
> (earlier rulings, both now satisfied - #17 and #19 are closed)

> "1. เลือก แยก run() แล้วให้ Airflow เรียกฟังก์ชัน อย่าส่งพอร์ตโฟลิโอที่เป็น
> BashOperator เรียงสิบบรรทัด... Airflow ไม่ได้คิดยอดบัญชี ให้แค่จัดลำดับและ
> ส่งงวด กฎอยู่ในโค้ดที่เทสได้"
> (operator choice - call existing functions, not BashOperator wrapping
> the CLI; confirmed correct after checking the code, see Exploration)

> "2. เลือก 1 DAG งานปิดงวด ก่อน อย่าแยกด้วย TriggerDagRunOperator / Dataset
> ในรอบนี้... อย่าขายว่า 1 DAG Run = 1 period ให้ขายว่า 1 DAG Run = ปิดงวดนี้
> + รีเฟรชตารางที่ขึ้นกับทุกงวด"
> (one DAG, tasks labeled by scope, not split into separate graphs)

> "3. เลือก trigger มือ ใส่ company/year/period ทุกครั้ง schedule=None...
> อย่าตั้ง cron รายเดือนตอนนี้"
> (manual trigger with `--conf`, no schedule yet)

> "4. เลือก task สุดท้ายใน DAG fail แล้ว DAG แดง... อย่ารัน checks.py แยกมือ
> หลังจบแล้วถือว่าผ่าน"
> (checks are a real gate task, not a manual afterthought)

> "Q1 กลับคำ... 7/8 script มี core function แยกจาก main() อยู่แล้ว ไม่ต้อง
> 'แยก run()' ใหม่ แค่ import เรียกตรง"
> (my own correction, put back to you and confirmed, after actually
> reading every script's `main()` instead of assuming)

## Exploration

**Every script's `main()`, read directly, not assumed** - this is what
decided the operator question. `git grep "^def "` first, then the actual
body of each `main()`:

| Script | Core function already exists | What an Airflow task must call |
|---|---|---|
| `load_stg.py` | no - logic is inline in `main()` | `main()` itself, unchanged - it takes no args, no CLI branch to skip |
| `load_fact.py` | `load_period(con, company, year, period)` | 4 calls in order: `load_map_account`, `ensure_tables`, then per period `verify_rollback_safety` + `load_period` |
| `quality_gate.py` | `run_gate(con, scope_filter)` | **nothing** - already runs inside `load_fact.py`'s `load_period()` |
| `reconcile_account.py` | `build_recon_period_summary(con, periods=None)` | one call |
| `reconcile_reversals.py` | `build_recon_reversal_pairs(con)` | one call |
| `reconcile_mismatch.py` | `build_recon_mismatch(con, periods=None)` | one call |
| `build_period_report.py` | no single entry point - `main()` chains 5 calls (`build_period_report`, `build_controller_pack`, `build_exceptions_appendix`, the private `_fetch`, `write_period_signoff`) | needs one new small wrapper function |
| `build_analyst_view.py` | `build_fact_gl_line_ready(con)` | one call |
| `checks.py` | n/a, not part of the close DAG | see below - can't be reused as written |

`load_stg.py` and `checks.py` share the same shape: neither branches on
`sys.argv`, so both are callable as-is with zero extraction. That's a
fact worth having before writing any DAG code, not something to
discover by trial and error once the file exists.

**`checks.py` cannot be the DAG's final gate as written.** It pins exact
numbers to periods 1-3 - `P01_FACT_ANCHOR = (13140, 3517, 97144587.13)`,
`mismatch_known_counts`'s exact 17/200/2 split, and others. Running it
against a newly closed period 4 would fail on anchors that were never
meant to apply there, not because anything is actually wrong. This
isn't new information changing scope - it's why the gate task needs its
own, smaller, general-invariant check set, tracked as a non-goal below
rather than folded in here.

**Concurrency is a real risk, not a hypothetical one, checked against a
named pattern instead of invented.** `warehouse.duckdb` is one file,
single-writer. `reconcile_account.py` and `reconcile_mismatch.py`
already rebuild every loaded period on every call, regardless of which
period triggered the run. Two DAG Runs at once would race on the same
file. Checked `marker_out/Data-Engineering-Design-Patterns-121525` (the
project's own cited source, Konieczny's *Data Engineering Design
Patterns*) rather than assume a fix: this is exactly the **Single
Runner** pattern (ch. Orchestration), whose own worked example
configures `max_active_runs=1` on an Airflow DAG for precisely this
reason - a sequential pipeline where concurrent runs produce wrong
results, not just slow ones.

**Airflow's own environment needs two things it doesn't have yet.**
`@task`/PythonOperator runs in-process inside Airflow's worker, not a
subprocess - so `~/airflow/.venv` (the uv-managed Python 3.12 venv from
mission 18's install) needs `duckdb` installed, and
`finance-migration-batch/src` needs to be importable (`sys.path` or an
installed package), or `import load_fact` fails at DAG parse time, not
run time. This wasn't a concern under the original BashOperator plan,
since a subprocess can shell out to any interpreter regardless of what
Airflow's own venv has installed - it's a direct, checked consequence
of switching to `@task`, not optional.

## Desired outcomes

- `dags/gl_period_close.py` (or equivalent), defining the 7-task chain
  (`load_stg`, `load_fact`, `reconcile_account`, `reconcile_reversals`,
  `reconcile_mismatch`, `build_period_report`, `build_analyst_view`)
  plus a final `checks` task, wired with `>>` in the same order
  `docs/runbook.md` already documents.
- `quality_gate.py` does not appear as its own task.
- `max_active_runs=1` set on the DAG, with a comment citing the Single
  Runner pattern so a future reader isn't left guessing why.
- `schedule=None`, `catchup=False`, period identified via
  `params`/`dag_run.conf`, no default period.
- `build_period_report.py` gets one small new wrapper function; no
  other `src/*.py` file's logic changes.
- Airflow's venv has what it needs to actually import and run the
  pipeline's functions, verified by a real trigger, not assumed from
  the DAG parsing without error.

## Deterministic checks

- [ ] DAG file parses with no import errors inside Airflow's own venv.
- [ ] Task graph in the Airflow UI matches the 8-step runbook order
      (7 pipeline tasks + 1 checks task), `quality_gate` absent as its
      own node.
- [ ] `reconcile_reversals` task precedes `reconcile_mismatch` -
      verified as a graph edge, not just present in the file.
- [ ] `max_active_runs=1` present in the DAG definition.
- [ ] A real manual trigger (`--conf` with a genuine test period) runs
      end to end against the real warehouse; resulting row counts,
      `dq_violations`, and report match what running
      `docs/runbook.md`'s manual sequence produces for the same period.
- [ ] `src/checks.py` still 72/72 against the real dataset, unaffected -
      confirms this ticket touched orchestration only, no reconciliation
      logic.
- [ ] `git diff --stat` shows no changes inside any existing function
      body in `src/*.py` other than the one new wrapper in
      `build_period_report.py`.

## Non-goals

- Not building the DAG's own smaller check subset (`src/checks.py`
  stays exactly what it is - the real-anchor CI/regression suite).
  Separate ticket once this one closes.
- Not adding a `schedule`. Stays `None` until a real per-period source
  file exists on a real cadence with something to check readiness
  against.
- Not splitting into multiple DAGs. Revisit only if the reversal-pairs
  refresh becomes expensive enough on its own to want decoupling, or the
  warehouse moves off a single DuckDB file - neither is true today.
- Not updating `docs/de-checklist.md`'s "not done in first pass" line
  for Airflow yet - that's a result of this ticket closing, not a
  precondition for starting it.

## Human approvals

**Before build:** none needed beyond the grilling round and its
follow-up correction - operator choice, DAG count, trigger model, and
gate placement were all locked there, including the one place I got it
wrong the first time and put the correction back to you rather than
quietly fixing it myself.

**Before the output is used:** confirm a real trigger against the real
warehouse produces the same numbers the manual runbook sequence does,
then comment "approved" on #20.

## Retro

(written after build and verification)
