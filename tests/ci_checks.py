"""CI's check surface. Ticket 18. Different purpose than src/checks.py,
not a smaller copy of it - proves the gate mechanism fires correctly on
6 known scenarios in tests/fixtures/journal_entries_ci.parquet, not that
this period's real numbers match a real close. Never expect this file's
assertions to hold against the real dataset, and never expect
src/checks.py's real anchors (P01's 97,144,587.13, the 174,944 document
count, etc.) to hold here - two different questions, two separate files.

Runs the real src/*.py scripts as subprocesses, exactly as documented in
docs/runbook.md, not by importing their functions - a script broken at
its own CLI entrypoint (wrong argv handling, an import that no longer
resolves) fails here even when every function inside it still imports
cleanly. Scope is company_code=9999, fiscal_year=2099, fiscal_period=1 -
see tests/fixtures/build_ci_fixture.py for why that can never collide
with the real project scope.

Run: python tests/ci_checks.py
"""

import os
import subprocess
import sys
from pathlib import Path

import duckdb  # type: ignore

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "journal_entries_ci.parquet"
CI_WAREHOUSE = REPO_ROOT / "tests" / "fixtures" / ".ci_warehouse.duckdb"
# build_period_report.py's paths aren't overridable via env var (by
# design - see src/build_period_report.py's own docstring), so its 3
# files land in the real reports/ dir. fiscal_year=2099 can't collide
# with or overwrite a real report, but they'd linger as stray untracked
# files on a local run - clean up after.
CI_REPORT_FILES = [
    REPO_ROOT / "reports" / "period_2099-01.md",
    REPO_ROOT / "reports" / "controller_pack_2099-01.md",
    REPO_ROOT / "reports" / "exceptions_2099-01.md",
]

COMPANY, YEAR, PERIOD = 9999, 2099, 1
PF = f"company_code = {COMPANY} AND fiscal_year = {YEAR} AND fiscal_period = {PERIOD}"

ENV = dict(os.environ, GL_SOURCE_PATH=str(FIXTURE), GL_WAREHOUSE_PATH=str(CI_WAREHOUSE))


def _run(*args: str) -> None:
    subprocess.run([sys.executable, *args], cwd=REPO_ROOT, env=ENV, check=True)


def run_pipeline() -> None:
    CI_WAREHOUSE.unlink(missing_ok=True)
    _run("src/load_stg.py")
    _run("src/load_fact.py", str(COMPANY), str(YEAR), str(PERIOD))
    _run("src/reconcile_account.py")
    # reconcile_mismatch.py LEFT JOINs recon_reversal_pairs, which only
    # this script creates - a truly fresh warehouse has no such table
    # yet. Run once, not per-period (mission 07: not period-scoped).
    # Scrutinize caught docs/runbook.md missing this exact step too.
    _run("src/reconcile_reversals.py")
    _run("src/reconcile_mismatch.py")
    # build_analyst_view.py joins period_signoff, which only
    # build_period_report.py writes (ADR-0008) - matches the real
    # runbook.md sequence, which already has this step in the right
    # order; this pipeline just hadn't caught up to it yet.
    _run("src/build_period_report.py", str(COMPANY), str(YEAR), str(PERIOD))
    _run("src/build_analyst_view.py")


def pipeline_ran_end_to_end(con):
    got = con.execute(f"SELECT COUNT(*) FROM stg_gl WHERE {PF}").fetchone()[0]
    return got == 15, f"stg_gl rows for CI scope={got} (want 15) - a nonzero count here means every script above exited 0"


def normal_document_loads_clean(con):
    fact_rows = con.execute(f"""
        SELECT COUNT(*) FROM fact_gl_line WHERE {PF} AND document_id = 'CI-DOC-NORMAL-001'
    """).fetchone()[0]
    dq_rows = con.execute(f"""
        SELECT COUNT(*) FROM dq_violations WHERE {PF} AND document_id = 'CI-DOC-NORMAL-001'
    """).fetchone()[0]
    ok = fact_rows == 2 and dq_rows == 0
    return ok, f"fact_gl_line rows={fact_rows} (want 2), dq_violations rows={dq_rows} (want 0)"


def unbalanced_document_excluded(con):
    fact_rows = con.execute(f"""
        SELECT COUNT(*) FROM fact_gl_line WHERE {PF} AND document_id = 'CI-DOC-UNBALANCED-001'
    """).fetchone()[0]
    blocking = con.execute(f"""
        SELECT COUNT(*) FROM dq_violations
        WHERE {PF} AND document_id = 'CI-DOC-UNBALANCED-001'
          AND check_name = 'unbalanced_document' AND blocking = true
    """).fetchone()[0]
    ok = fact_rows == 0 and blocking > 0
    return ok, f"in fact_gl_line={fact_rows} (want 0), logged blocking={blocking} (want >0)"


def ab_broadcast_detected(con):
    fact_rows = con.execute(f"""
        SELECT COUNT(*) FROM fact_gl_line WHERE {PF} AND document_id = 'CI-DOC-AB-001'
    """).fetchone()[0]
    flagged = con.execute(f"""
        SELECT COUNT(*) FROM dq_violations
        WHERE {PF} AND document_id = 'CI-DOC-AB-001'
          AND check_name = 'local_amount_imbalance' AND blocking = false
    """).fetchone()[0]
    ok = fact_rows == 4 and flagged > 0
    return ok, f"in fact_gl_line={fact_rows} (want 4, non-blocking), local_amount_imbalance logged={flagged} (want >0)"


def opening_balance_flagged_not_excluded(con):
    got = con.execute(f"""
        SELECT COUNT(*) FROM fact_gl_line
        WHERE {PF} AND document_id = 'CI-DOC-OPENBAL-001' AND is_opening_balance = true
    """).fetchone()[0]
    return got == 2, f"flagged is_opening_balance rows={got} (want 2 - present, not excluded)"


def duplicate_grain_excluded(con):
    """The whole document is excluded, not just the duplicated line -
    verified against a real run, not assumed from reading the query.
    Duplicating line_number=1 also doubles it in the document's own
    debit/credit sum, so unbalanced_document correctly fires too (the
    duplicate is phantom debit as far as that check can tell) -
    document-grain, so it excludes every line, including the
    non-duplicated one. Two independent, correct findings on one
    document, not a bug - checked that duplicate_source is one of them,
    not that it's the only one."""
    dup_line = con.execute(f"""
        SELECT COUNT(*) FROM fact_gl_line
        WHERE {PF} AND document_id = 'CI-DOC-DUP-001' AND line_number = 1
    """).fetchone()[0]
    other_line = con.execute(f"""
        SELECT COUNT(*) FROM fact_gl_line
        WHERE {PF} AND document_id = 'CI-DOC-DUP-001' AND line_number = 2
    """).fetchone()[0]
    blocking = con.execute(f"""
        SELECT COUNT(*) FROM dq_violations
        WHERE {PF} AND document_id = 'CI-DOC-DUP-001' AND check_name = 'duplicate_source' AND blocking = true
    """).fetchone()[0]
    ok = dup_line == 0 and other_line == 0 and blocking > 0
    return ok, f"duplicated line_number=1 in fact_gl_line={dup_line} (want 0), line_number=2 in fact_gl_line={other_line} (want 0, excluded document-grain), duplicate_source logged blocking={blocking} (want >0)"


def unmapped_account_logged_not_excluded(con):
    """Fixed by mission 17: quality_gate.py's unmapped_account query now
    LEFT JOINs map_account instead of matching an IN-list built only
    from rows already inside the file, so a gl_account with zero rows
    in map_account.csv (this fixture's 999888) gets caught too - not
    just accounts present but tagged status='unmapped'. Was a known,
    pinned gap (issue #17) until this fix; this check now asserts the
    real, current, fixed behavior, not the old gap."""
    fact_rows = con.execute(f"""
        SELECT COUNT(*) FROM fact_gl_line WHERE {PF} AND document_id = 'CI-DOC-UNMAPPED-001'
    """).fetchone()[0]
    logged = con.execute(f"""
        SELECT COUNT(*) FROM dq_violations
        WHERE {PF} AND document_id = 'CI-DOC-UNMAPPED-001'
          AND check_name = 'unmapped_account' AND blocking = false
    """).fetchone()[0]
    ok = fact_rows == 2 and logged > 0
    return ok, f"in fact_gl_line={fact_rows} (want 2, non-blocking), unmapped_account logged={logged} (want >0)"


def idempotent_reload(before: tuple) -> tuple:
    """Takes the "before" snapshot already read by the caller, not a
    connection - a read-only connection held open in this process while
    the reload subprocess writes the same file would contend with it.
    The caller closes its connection before calling this, and reopens a
    fresh one after, so there's never a reader and a writer on the file
    at once."""
    _run("src/load_fact.py", str(COMPANY), str(YEAR), str(PERIOD))
    con = duckdb.connect(str(CI_WAREHOUSE), read_only=True)
    after = con.execute(f"""
        SELECT COUNT(*), ROUND(SUM(local_amount), 2) FROM fact_gl_line WHERE {PF}
    """).fetchone()
    con.close()
    return before == after, f"before reload={before}  after reload={after}"


# (name, fn) for the ordinary read-only checks. idempotent_reload runs
# separately in main(), since it needs the connection closed first.
CHECKS = [
    ("pipeline ran end to end", pipeline_ran_end_to_end),
    ("normal document loads clean", normal_document_loads_clean),
    ("unbalanced document excluded", unbalanced_document_excluded),
    ("AB broadcast detected", ab_broadcast_detected),
    ("opening balance flagged, not excluded", opening_balance_flagged_not_excluded),
    ("duplicate grain excluded", duplicate_grain_excluded),
    ("unmapped account logged, not excluded", unmapped_account_logged_not_excluded),
]


def main() -> int:
    run_pipeline()
    con = duckdb.connect(str(CI_WAREHOUSE), read_only=True)
    results = []
    for name, fn in CHECKS:
        try:
            ok, detail = fn(con)
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"error: {exc}"
        results.append((name, ok, detail))

    # idempotent_reload needs the file free of any open reader before its
    # own subprocess can write to it.
    before = con.execute(f"""
        SELECT COUNT(*), ROUND(SUM(local_amount), 2) FROM fact_gl_line WHERE {PF}
    """).fetchone()
    con.close()
    try:
        ok, detail = idempotent_reload(before)
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, f"error: {exc}"
    results.append(("idempotent reload", ok, detail))

    failed = 0
    for name, ok, detail in results:
        print(f"{'ok  ' if ok else 'FAIL'}  {name:<40} {detail}")
        failed += not ok
    CI_WAREHOUSE.unlink(missing_ok=True)
    for f in CI_REPORT_FILES:
        f.unlink(missing_ok=True)
    print(f"\n{len(results) - failed}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
