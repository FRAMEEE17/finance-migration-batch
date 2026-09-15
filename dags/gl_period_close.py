"""Airflow DAG for the existing period-close pipeline. Mission 20.

Wraps the same 7 steps docs/runbook.md already documents, calling each
script's existing core function directly - not through the CLI. Every
task's docstring below says exactly which function it calls and why,
matching mission 20's own per-script table (checked against the real
source, not assumed). No SQL or business logic lives in this file; it
only sequences and parameterizes what src/checks.py already verifies
against real data.

quality_gate.py is not a task here - it already runs inside load_fact's
load_period(). checks.py still isn't a task - it pins exact numbers to
periods 1-3 and can't be a general period gate (mission 20's
Non-goals). period_close_gate.py (mission 21) is that general gate: the
DAG's last task, reading what every task before it already produced and
deciding, for whatever period this run asked for, whether it's actually
closeable.

Lives in the repo, not in ~/airflow/dags/ - Airflow's dags_folder
(airflow.cfg) points here directly, so this file is the one thing
Airflow parses and the one thing tracked in git. No copy to keep in
sync.

Trigger manually, one period at a time - see the Single Runner note
below for why:

  airflow dags trigger gl_period_close \
    --conf '{"company_code":1000,"fiscal_year":2024,"fiscal_period":3}'
"""

import sys
from pathlib import Path

REPO_SRC = Path(__file__).resolve().parent.parent / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

import duckdb  # type: ignore
from airflow.providers.smtp.notifications.smtp import SmtpNotifier  # type: ignore
from airflow.sdk import DAG, Param, task, get_current_context # type: ignore

from config import WAREHOUSE_DB  # type: ignore

# Mission 21, issue #24: fires once a task's retries are exhausted -
# Airflow only calls on_failure_callback when a task instance actually
# reaches the `failed` state, which a retry that still has attempts left
# does not (it goes to `up_for_retry` instead). No extra "did retries run
# out" logic needed; this is what that state transition already means.
# smtp_default connection (issue #21's decision) points at a local debug
# SMTP server for testing, not a real mailbox - see docs/runbook.md.
FAILURE_NOTIFIER = SmtpNotifier(
    from_email="gl-period-close@finance-migration-batch.local",
    to="oncall@finance-migration-batch.local",
    subject="gl_period_close FAILED: {{ ti.task_id }} (attempt {{ ti.try_number }})",
    html_content="""
        <p>DAG run: {{ dag_run.run_id }}</p>
        <p>Task: {{ ti.task_id }}, attempt {{ ti.try_number }}</p>
        <p>Requested period: company={{ params.company_code }}
           year={{ params.fiscal_year }} period={{ params.fiscal_period }}</p>
        <p>Exception: {{ exception }}</p>
        <p>Evidence: reports/airflow_runs/{{ dag_run.run_id }}/{{ ti.task_id }}__attempt{{ ti.try_number }}.json</p>
    """,
)


def _period_params(ctx) -> tuple[int, int, int]:
    p = ctx["params"]
    return p["company_code"], p["fiscal_year"], p["fiscal_period"]


def _with_evidence(task_id, fn, check_inputs=False):
    """Mission 21 (issue #23): wraps a task's real body, records the
    outcome (success/failed/rejected) as evidence after. check_inputs
    additionally checks this attempt's source/mapping hashes against
    the same DAG run's earlier attempt of this same task before running
    anything, rejecting a clear+retry whose inputs changed underneath
    it - only load_stg and load_fact pass check_inputs=True, since
    they're the only two tasks that actually read those files
    (scrutinize finding: checking it on every task let an unrelated
    task's retry get rejected over a file it never reads). See
    src/airflow_run_evidence.py."""
    import airflow_run_evidence
    ctx = get_current_context()
    company, year, period = _period_params(ctx)
    run_id = ctx["dag_run"].run_id
    attempt = ctx["ti"].try_number
    return airflow_run_evidence.run_with_evidence(
        run_id, task_id, attempt, company, year, period, fn, check_inputs=check_inputs
    )


with DAG(
    dag_id="gl_period_close",
    description="Close one fiscal period through the existing pipeline scripts, in order.",
    schedule=None,
    catchup=False,
    # Single Runner pattern (Konieczny, Data Engineering Design Patterns,
    # ch. Orchestration): warehouse.duckdb is one file, single-writer.
    # reconcile_account and reconcile_mismatch already rebuild every
    # loaded period on every call, regardless of which period triggered
    # the run - two DAG Runs at once would race on the same file. This
    # is a correctness requirement, not a throughput setting.
    max_active_runs=1,
    # Safe because every task below is: load_stg/load_fact are proven by
    # verify_rollback_safety, the three reconcile_* tasks and
    # write_period_signoff all DELETE ... WHERE {pf} then INSERT (never
    # append), re-verified twice this session with byte-identical P02/P03
    # reruns. A retry redoes exactly what a first attempt would have.
    default_args={"retries": 1, "on_failure_callback": FAILURE_NOTIFIER},
    params={
        # No defaults, on purpose - combined with schedule=None, Airflow
        # validates these at trigger time instead of at DAG-parse time,
        # so there is no default period a bare trigger could run
        # silently (mission 20's own requirement).
        "company_code": Param(type="integer", title="Company code"),
        "fiscal_year": Param(type="integer", title="Fiscal year"),
        "fiscal_period": Param(type="integer", title="Fiscal period"),
    },
    tags=["finance-migration-batch"],
) as dag:

    @task
    def load_stg():
        """Calls load_stg.main() unchanged. It takes no args - no CLI
        branch to skip, so nothing to extract."""
        def _run():
            import load_stg
            rc = load_stg.main()
            if rc != 0:
                raise RuntimeError(f"load_stg.main() exited {rc} - row count or schema check failed")
        return _with_evidence("load_stg", _run, check_inputs=True)

    @task
    def load_fact():
        """4 calls, in the same order load_fact.py's own main() runs
        them: load_map_account, ensure_tables, then per period
        verify_rollback_safety + load_period. quality_gate.py's
        run_gate() executes inside load_period() - it is not a
        separate task."""
        def _run():
            import load_fact
            company, year, period = _period_params(get_current_context())
            con = duckdb.connect(str(WAREHOUSE_DB))
            try:
                load_fact.load_map_account(con)
                load_fact.ensure_tables(con)
                load_fact.verify_rollback_safety(con, company, year, period)
                return load_fact.load_period(con, company, year, period)
            finally:
                con.close()
        return _with_evidence("load_fact", _run, check_inputs=True)

    @task
    def reconcile_account():
        """build_recon_period_summary(con, None) - no period arg, same
        as docs/runbook.md's own call. Rebuilds every period currently
        in fact_gl_line, not just the one this run closed."""
        def _run():
            import reconcile_account
            con = duckdb.connect(str(WAREHOUSE_DB))
            try:
                n = reconcile_account.build_recon_period_summary(con, None)
            finally:
                con.close()
            return {"rows": n}
        return _with_evidence("reconcile_account", _run)

    @task
    def reconcile_reversals():
        """build_recon_reversal_pairs(con). Not period-scoped (mission
        07) - must run at least once before reconcile_mismatch on any
        warehouse, which is exactly why it is a task in this chain and
        not something run once and forgotten (mission 18's real
        crash)."""
        def _run():
            import reconcile_reversals
            con = duckdb.connect(str(WAREHOUSE_DB))
            try:
                n = reconcile_reversals.build_recon_reversal_pairs(con)
            finally:
                con.close()
            return {"pairs": n}
        return _with_evidence("reconcile_reversals", _run)

    @task
    def reconcile_mismatch():
        """build_recon_mismatch(con, None) - same no-args, rebuild-every-
        loaded-period behavior as reconcile_account. Runs after
        reconcile_reversals: recon_reversal_pairs must already exist."""
        def _run():
            import reconcile_mismatch
            con = duckdb.connect(str(WAREHOUSE_DB))
            try:
                n = reconcile_mismatch.build_recon_mismatch(con, None)
            finally:
                con.close()
            return {"rows": n}
        return _with_evidence("reconcile_mismatch", _run)

    @task
    def build_period_report():
        """Calls build_period_report.run() - the one new function this
        mission added, mirroring main()'s own 5-call sequence
        (build_period_report, build_controller_pack,
        build_exceptions_appendix, _fetch, write_period_signoff) minus
        argv parsing. Nothing inside those 4 existing functions
        changed."""
        def _run():
            import build_period_report
            company, year, period = _period_params(get_current_context())
            con = duckdb.connect(str(WAREHOUSE_DB))
            try:
                paths = build_period_report.run(con, company, year, period)
            finally:
                con.close()
            return {k: str(v) for k, v in paths.items()}
        return _with_evidence("build_period_report", _run)

    @task
    def build_analyst_view():
        """build_fact_gl_line_ready(con). Rebuilds fact_gl_line_ready
        for every accepted period, same as running the script by
        hand."""
        def _run():
            import build_analyst_view
            con = duckdb.connect(str(WAREHOUSE_DB))
            try:
                build_analyst_view.build_fact_gl_line_ready(con)
            finally:
                con.close()
        return _with_evidence("build_analyst_view", _run)

    @task
    def period_close_gate():
        """run_period_close_gate(con, company, year, period) - mission 21.
        Read-only: rebuilds nothing, just decides whether the period the
        seven tasks above just produced is actually closeable. Raises
        PeriodCloseGateError (with every reason found, not just the
        first) on failure, which fails this task and the DAG Run."""
        def _run():
            import period_close_gate
            company, year, period = _period_params(get_current_context())
            con = duckdb.connect(str(WAREHOUSE_DB), read_only=True)
            try:
                period_close_gate.run_period_close_gate(con, company, year, period)
            finally:
                con.close()
        return _with_evidence("period_close_gate", _run)

    (
        load_stg()
        >> load_fact() # type: ignore
        >> reconcile_account()
        >> reconcile_reversals()
        >> reconcile_mismatch()
        >> build_period_report()
        >> build_analyst_view()
        >> period_close_gate()
    ) # type: ignore
