"""Airflow DAG for the existing period-close pipeline. Mission 20.

Wraps the 7 steps docs/runbook.md documents, calling each script's core
function directly, not the CLI. No SQL or business logic here; it only
sequences what src/checks.py already verifies.

quality_gate.py runs inside load_fact's load_period(), not as its own
task. checks.py pins exact numbers to periods 1-3, so it can't be a
general gate either - period_close_gate.py (mission 21) is that gate,
the DAG's last task.

Lives in the repo, not ~/airflow/dags/: airflow.cfg's dags_folder points
here directly.

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

# Fires when retries are exhausted (mission 21, issue #24) - see
# docs/runbook.md's Airflow section for why html_content skips
# {{ exception }} and where the full detail actually lives.
FAILURE_NOTIFIER = SmtpNotifier(
    from_email="gl-period-close@finance-migration-batch.local",
    to="oncall@finance-migration-batch.local",
    subject="gl_period_close FAILED: {{ ti.task_id }} (attempt {{ ti.try_number }})",
    html_content="""
        <p>DAG run: {{ dag_run.run_id }}</p>
        <p>Task: {{ ti.task_id }}, attempt {{ ti.try_number }}</p>
        <p>Requested period: company={{ params.company_code }}
           year={{ params.fiscal_year }} period={{ params.fiscal_period }}</p>
        <p>Exception detail: see the evidence file below - not available
           directly in this template.</p>
        <p>Evidence: reports/airflow_runs/{{ dag_run.run_id }}/{{ ti.task_id }}__attempt{{ ti.try_number }}.json</p>
    """,
)


def _period_params(ctx) -> tuple[int, int, int]:
    p = ctx["params"]
    return p["company_code"], p["fiscal_year"], p["fiscal_period"]


DEMO_OFF = "none"  # sentinel default for both demo params, see below


def _warehouse_path(ctx) -> Path:
    """Mission 21 demo hook (issue #25): demo_warehouse_path lets one
    trigger's --conf point every task at a throwaway warehouse copy.
    DEMO_OFF is the default and falls back to the real WAREHOUSE_DB. A
    per-run param, not an env var, so Clear can preserve it on retry.

    The path must already exist. duckdb.connect() otherwise creates an
    empty file silently, and the run would reconcile nothing against no
    data - fail loud instead."""
    p = ctx["params"].get("demo_warehouse_path")
    if not p or p == DEMO_OFF:
        return WAREHOUSE_DB
    path = Path(p)
    if not path.exists():
        raise RuntimeError(
            f"demo_warehouse_path={p!r} does not exist. This must point at an "
            f"already-existing copy of the warehouse (e.g. cp warehouse.duckdb "
            f"warehouse_demo.duckdb first) - duckdb.connect() would otherwise "
            f"silently create a new, empty file here and the whole run would "
            f"reconcile nothing against no data. Leave this field blank for a "
            f"normal run against the real warehouse."
        )
    return path


# warehouse.duckdb and reports/airflow_runs/ are plain local paths, not
# executor-aware - see docs/runbook.md for why a distributed executor
# needs shared storage or this check loosened deliberately.
_SHARED_FILESYSTEM_EXECUTORS = {"LocalExecutor", "SequentialExecutor", "DebugExecutor"}


def _assert_shared_filesystem_executor() -> None:
    from airflow.configuration import conf # type: ignore
    executor = conf.get("core", "executor")
    if executor not in _SHARED_FILESYSTEM_EXECUTORS:
        raise RuntimeError(
            f"gl_period_close requires every task attempt to see the same local "
            f"filesystem (warehouse.duckdb, reports/airflow_runs/ evidence) - "
            f"configured executor is {executor!r}, not one of "
            f"{sorted(_SHARED_FILESYSTEM_EXECUTORS)}. Safe under a distributed "
            f"executor only if warehouse.duckdb and reports/ both sit on shared "
            f"storage mounted identically on every worker - if that's genuinely "
            f"true here, this check is wrong for your deployment and should be "
            f"loosened deliberately, not silently bypassed."
        )


def _with_evidence(task_id, fn, check_inputs=False):
    """Wraps a task's body and records the outcome as evidence (mission
    21, issue #23 - src/airflow_run_evidence.py). check_inputs=True only
    for load_stg/load_fact, the two tasks that actually read the source
    files it hashes; rejects a clear+retry whose inputs changed
    underneath it."""
    _assert_shared_filesystem_executor()
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
    # Single Runner pattern (Konieczny, ch. Orchestration): warehouse.duckdb
    # is one file, single-writer; two DAG Runs would race on it.
    max_active_runs=1,
    # Idempotent: load_stg/load_fact via verify_rollback_safety, the
    # reconcile_* tasks and write_period_signoff via DELETE-then-INSERT,
    # never append. A retry redoes exactly what a first attempt would.
    default_args={"retries": 1, "on_failure_callback": FAILURE_NOTIFIER},
    params={
        # No defaults - with schedule=None, Airflow validates these at
        # trigger time, so no bare trigger can run a default period silently.
        "company_code": Param(type="integer", title="Company code"),
        "fiscal_year": Param(type="integer", title="Fiscal year"),
        "fiscal_period": Param(type="integer", title="Fiscal period"),
        # Demo-only (issue #25); default DEMO_OFF leaves a normal run unaffected.
        "demo_warehouse_path": Param(default=DEMO_OFF, type="string", title="Demo only: override warehouse.duckdb path (leave as \"none\" for a normal run)"),
        "demo_inject_fault_task": Param(default=DEMO_OFF, type="string", title="Demo only: task_id to fail after it completes its real work (leave as \"none\" for a normal run)"),
    },
    tags=["finance-migration-batch"],
) as dag:

    @task
    def load_stg():
        """Calls load_stg.main(), passing the demo warehouse override
        (issue #25) through explicitly - the one script whose only
        warehouse-path hook was an env var baked in at import time, too
        early for a per-run param to reach."""
        def _run():
            import load_stg
            rc = load_stg.main(warehouse_db=_warehouse_path(get_current_context()))
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
            ctx = get_current_context()
            company, year, period = _period_params(ctx)
            con = duckdb.connect(str(_warehouse_path(ctx)))
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
            con = duckdb.connect(str(_warehouse_path(get_current_context())))
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
            con = duckdb.connect(str(_warehouse_path(get_current_context())))
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
            ctx = get_current_context()
            con = duckdb.connect(str(_warehouse_path(ctx)))
            try:
                n = reconcile_mismatch.build_recon_mismatch(con, None)
            finally:
                con.close()
            # Demo fault injection (issue #25, docs/runbook.md): fires only
            # after the real rebuild above wrote real data, and only when
            # both the trigger param and this flag file are set. Gated on
            # the flag file, not just the param, because Clear preserves a
            # DagRun's original conf - the flag file is the removable part.
            if ctx["params"].get("demo_inject_fault_task") == "reconcile_mismatch" and Path(
                "/tmp/gl_period_close_demo_fault_flag"
            ).exists():
                raise RuntimeError(
                    "mission 21 demo: deliberate fault injected after reconcile_mismatch "
                    f"completed its rebuild ({n} rows written) - remove "
                    "/tmp/gl_period_close_demo_fault_flag to recover"
                )
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
            ctx = get_current_context()
            company, year, period = _period_params(ctx)
            con = duckdb.connect(str(_warehouse_path(ctx)))
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
            con = duckdb.connect(str(_warehouse_path(get_current_context())))
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
            ctx = get_current_context()
            company, year, period = _period_params(ctx)
            con = duckdb.connect(str(_warehouse_path(ctx)), read_only=True)
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
