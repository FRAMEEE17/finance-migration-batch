"""Period-close gate. Mission 21, issue #22.

The DAG's actual last task. Decides whether the period load_fact through
build_analyst_view just processed is genuinely closeable, by reading what
those tasks already produced - it never rebuilds a table and never calls
checks.main() (checks.py pins numbers to periods 1-3 and can't run as a
general gate; see mission 20's non-goals).

A period passes only if every check below passes. Every check that fails
is collected, not just the first one - an operator reading the DAG log
should see the whole picture in one failure, not fix one thing and
re-trigger to discover the next.

Run: python src/period_close_gate.py <company_code> <fiscal_year> <fiscal_period>
"""

import sys
from pathlib import Path
from typing import List

import duckdb  # type: ignore

from build_period_report import controller_pack_path, exceptions_path, report_path
from config import WAREHOUSE_DB


class PeriodCloseGateError(Exception):
    """Raised with every reason the period failed, joined into one message."""


def _period_filter(company_code: int, fiscal_year: int, fiscal_period: int) -> str:
    return f"company_code = {company_code} AND fiscal_year = {fiscal_year} AND fiscal_period = {fiscal_period}"


def _check_signoff(con, pf: str, fiscal_year: int, fiscal_period: int, reasons: List[str]) -> bool:
    """Exactly one period_signoff row, accepted, pointing at the three
    real artifact files. Returns whether the period is even eligible for
    the checks below - there's nothing left to compare if this fails."""
    rows = con.execute(f"""
        SELECT recon_status, report_path, controller_pack_path, exceptions_path
        FROM period_signoff WHERE {pf}
    """).fetchall()

    if len(rows) == 0:
        reasons.append("no period_signoff row for this period")
        return False
    if len(rows) > 1:
        reasons.append(f"{len(rows)} period_signoff rows for this period, want exactly 1")
        return False

    recon_status, report_p, controller_p, exceptions_p = rows[0]
    if recon_status != "accepted":
        reasons.append(f"period_signoff.recon_status = {recon_status!r}, want 'accepted'")
        return False

    for label, recorded, want in [
        ("report", report_p, report_path(fiscal_year, fiscal_period)),
        ("controller_pack", controller_p, controller_pack_path(fiscal_year, fiscal_period)),
        ("exceptions", exceptions_p, exceptions_path(fiscal_year, fiscal_period)),
    ]:
        if recorded != str(want):
            reasons.append(f"period_signoff.{label}_path = {recorded!r}, want {str(want)!r}")
        elif not Path(recorded).exists():
            reasons.append(f"{label} file missing on disk: {recorded}")

    return True


def _check_account_reconciliation(con, pf: str, company_code: int, fiscal_year: int, fiscal_period: int, reasons: List[str]) -> None:
    """Recomputes each account's debit/credit gap straight from stg_gl and
    compares it to recon_period_summary - same arithmetic
    reconcile_account.py uses to build that table, run here read-only, so
    the gate isn't just trusting the stored table matches what's actually
    in stg_gl right now. Tolerance matches the project's 0.01 materiality
    rule (docs/business-rules.md) - DuckDB's parallel SUM is not
    associativity-safe: a fresh SUM over the same rows can differ from
    recon_period_summary's stored SUM by a full cent after independent
    ROUND(...,2) on each side, not just the sub-cent (~2e-7) drift
    _no_neg_zero in build_period_report.py already documents - measured
    directly against this dataset (max 0.0100000007 across every account
    in P01, repeatable across runs). Tolerance is set above that
    measured ceiling, not guessed."""
    bad = con.execute(f"""
        WITH recomputed AS (
            SELECT gl_account, ROUND(SUM(debit_amount) - SUM(credit_amount), 2) AS dc_gap
            FROM stg_gl WHERE {pf} GROUP BY 1
        ),
        mismatched AS (
            SELECT recomputed.gl_account, recomputed.dc_gap, r.dc_gap AS stored_dc_gap
            FROM recomputed
            JOIN recon_period_summary r
              ON r.gl_account = recomputed.gl_account
             AND r.company_code = {company_code} AND r.fiscal_year = {fiscal_year} AND r.fiscal_period = {fiscal_period}
            WHERE ABS(recomputed.dc_gap - r.dc_gap) > 0.02
        )
        SELECT COUNT(*) OVER () AS total, gl_account, dc_gap, stored_dc_gap
        FROM mismatched LIMIT 5
    """).fetchall()
    if bad:
        total = bad[0][0]
        sample = [row[1:] for row in bad]
        reasons.append(f"{total} account(s) where recon_period_summary.dc_gap disagrees with a fresh recompute from stg_gl by more than 0.02: {sample}")

    missing = con.execute(f"""
        SELECT COUNT(DISTINCT gl_account) FROM stg_gl s WHERE {pf}
        AND NOT EXISTS (
            SELECT 1 FROM recon_period_summary r
            WHERE r.gl_account = s.gl_account AND r.company_code = {company_code}
              AND r.fiscal_year = {fiscal_year} AND r.fiscal_period = {fiscal_period}
        )
    """).fetchone()[0]
    if missing:
        reasons.append(f"{missing} account(s) in stg_gl for this period with no recon_period_summary row at all")


def _check_mismatch_unknown_threshold(con, pf: str, reasons: List[str]) -> None:
    """Recomputes the unknown-mismatch percentage straight from
    recon_mismatch, on the raw (unrounded) value per the rule locked in
    issue #21 - not the value cached in period_signoff, which could be
    stale if recon_mismatch changed after the report was written."""
    total, unknown = con.execute(f"""
        SELECT COUNT(*), SUM((cause = 'unknown')::int) FROM recon_mismatch WHERE {pf}
    """).fetchone()
    if not total:
        return  # zero mismatches this period is a valid, passing state
    pct = 100.0 * unknown / total
    if pct > 20.0:
        reasons.append(f"unknown mismatches this period = {pct:.4f}% (unknown={unknown}/{total}), want <= 20%")


def _check_fact_grain_unique(con, pf: str, reasons: List[str]) -> None:
    """The grain this whole project is built on (CLAUDE.md): one row per
    company + document + line + fiscal period. A duplicate here would
    mean load_fact's period-replace broke, silently, sometime after
    verify_rollback_safety last checked it."""
    dupes = con.execute(f"""
        WITH grouped AS (
            SELECT company_code, document_id, line_number, COUNT(*) AS n
            FROM fact_gl_line WHERE {pf}
            GROUP BY 1, 2, 3 HAVING COUNT(*) > 1
        )
        SELECT COUNT(*) OVER () AS total, company_code, document_id, line_number, n
        FROM grouped LIMIT 5
    """).fetchall()
    if dupes:
        total = dupes[0][0]
        sample = [row[1:] for row in dupes]
        reasons.append(f"{total} duplicate grain row(s) in fact_gl_line for this period: {sample}")


def _check_analyst_view(con, pf: str, reasons: List[str]) -> None:
    """Once period_signoff says accepted, fact_gl_line_ready (a view, not
    a copy) must expose exactly this period's fact rows - no fewer, no
    more."""
    fact_n = con.execute(f"SELECT COUNT(*) FROM fact_gl_line WHERE {pf}").fetchone()[0]
    ready_n = con.execute(f"SELECT COUNT(*) FROM fact_gl_line_ready WHERE {pf}").fetchone()[0]
    if fact_n != ready_n:
        reasons.append(f"fact_gl_line_ready has {ready_n} rows for this period, fact_gl_line has {fact_n}")


def run_period_close_gate(con, company_code: int, fiscal_year: int, fiscal_period: int) -> None:
    pf = _period_filter(company_code, fiscal_year, fiscal_period)
    reasons: List[str] = []

    eligible = _check_signoff(con, pf, fiscal_year, fiscal_period, reasons)
    if eligible:
        _check_account_reconciliation(con, pf, company_code, fiscal_year, fiscal_period, reasons)
        _check_mismatch_unknown_threshold(con, pf, reasons)
        _check_fact_grain_unique(con, pf, reasons)
        _check_analyst_view(con, pf, reasons)

    if reasons:
        label = f"{company_code}/{fiscal_year}-{fiscal_period:02d}"
        raise PeriodCloseGateError(f"period {label} failed the close gate: " + "; ".join(reasons))


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: python src/period_close_gate.py <company_code> <fiscal_year> <fiscal_period>")
        return 1
    company_code, fiscal_year, fiscal_period = (int(v) for v in sys.argv[1:4])

    con = duckdb.connect(str(WAREHOUSE_DB), read_only=True)
    try:
        run_period_close_gate(con, company_code, fiscal_year, fiscal_period)
    except PeriodCloseGateError as e:
        print(f"FAILED: {e}")
        return 1
    finally:
        con.close()
    print(f"period {company_code}/{fiscal_year}-{fiscal_period:02d}: gate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
