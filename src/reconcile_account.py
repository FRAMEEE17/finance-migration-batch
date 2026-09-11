"""Account-level reconciliation. Ticket 6 / Mission 06, parameterized by
period in Ticket 10 / Mission 10.

Builds recon_period_summary: one row per (gl_account, fiscal_year,
fiscal_period) for whichever periods are being rebuilt, comparing stg_gl
to fact_gl_line. Separate columns for the real gap (debit vs credit,
which stays clean) and the known-broken one (local_amount, per mission
06's exploration) - a single net column would show the same distortion
the mission exists to explain, not fix.

This script never touches local_amount. It reports on the defect found
in mission 06 (and confirmed systemic across periods in mission 10); the
fix, if any, belongs to the source-data ticket that finding opened
(#13), not here.

Deletes and rebuilds ONLY the periods passed in - never the whole table.
Mission 10 found the earlier CREATE OR REPLACE TABLE version would have
silently wiped every already-built period's rows the moment a second
period was loaded. Two ways to call this:
  - build_recon_period_summary(con, periods=[(1000, 2024, 1)]) rebuilds
    just that one period, leaving every other period's rows untouched.
  - build_recon_period_summary(con) with no periods rebuilds for every
    period currently present in fact_gl_line (queried, not a separately
    maintained list) - the "whole-set summary" mode.
Both delete only the periods they are about to re-insert; neither ever
issues a bare DELETE/CREATE OR REPLACE against the full table.

Run: python src/reconcile_account.py [<company_code> <fiscal_year> <fiscal_period> ...]
  no args: rebuild for every period currently in fact_gl_line
  with args: rebuild only the given (company, year, period) triples,
             e.g. python src/reconcile_account.py 1000 2024 2 1000 2024 3
"""

import sys
from typing import List, Optional, Tuple

import duckdb  # type: ignore

from config import WAREHOUSE_DB
from quality_gate import ensure_dq_violations_table

Period = Tuple[int, int, int]  # (company_code, fiscal_year, fiscal_period)


def all_loaded_periods(con) -> List[Period]:
    rows = con.execute("""
        SELECT DISTINCT company_code, fiscal_year, fiscal_period FROM fact_gl_line ORDER BY 1, 2, 3
    """).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def _periods_sql(periods: List[Period], alias: str = "") -> str:
    """Always returns a single, self-contained parenthesized expression,
    e.g. "((p1) OR (p2))" - callers that append " AND ..." to this in the
    same WHERE clause must not have the AND silently bind to only the
    last OR-ed period (SQL's AND binds tighter than OR)."""
    prefix = f"{alias}." if alias else ""
    clauses = " OR ".join(
        f"({prefix}company_code = {c} AND {prefix}fiscal_year = {y} AND {prefix}fiscal_period = {p})"
        for c, y, p in periods
    )
    return f"({clauses})"


def ensure_table(con) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS recon_period_summary (
            company_code BIGINT, gl_account BIGINT, fiscal_year BIGINT, fiscal_period BIGINT,
            stg_debit_total DOUBLE, stg_credit_total DOUBLE, dc_gap DOUBLE,
            stg_local_total DOUBLE, fact_local_total DOUBLE, local_amount_gap DOUBLE,
            imbalanced_doc_count BIGINT, imbalanced_local_amount DOUBLE,
            excluded_unbalanced_doc_count BIGINT
        )
    """)


def build_recon_period_summary(con, periods: Optional[List[Period]] = None) -> int:
    ensure_table(con)
    ensure_dq_violations_table(con)
    if periods is None:
        periods = all_loaded_periods(con)
    if not periods:
        return 0

    scope = _periods_sql(periods)
    scope_s = _periods_sql(periods, alias="s")

    con.execute(f"DELETE FROM recon_period_summary WHERE {scope}")

    con.execute(f"""
        INSERT INTO recon_period_summary
        WITH stg AS (
            SELECT company_code, gl_account, fiscal_year, fiscal_period,
                   ROUND(SUM(debit_amount), 2) AS stg_debit_total,
                   ROUND(SUM(credit_amount), 2) AS stg_credit_total,
                   ROUND(SUM(local_amount), 2) AS stg_local_total
            FROM stg_gl WHERE {scope}
            GROUP BY 1, 2, 3, 4
        ),
        fact AS (
            SELECT company_code, gl_account, fiscal_year, fiscal_period,
                   ROUND(SUM(local_amount), 2) AS fact_local_total
            FROM fact_gl_line WHERE {scope}
            GROUP BY 1, 2, 3, 4
        ),
        imbalanced AS (
            SELECT s.company_code, s.gl_account, s.fiscal_year, s.fiscal_period,
                   COUNT(DISTINCT s.document_id) AS imbalanced_doc_count,
                   ROUND(SUM(s.local_amount), 2) AS imbalanced_local_amount
            FROM stg_gl s
            JOIN dq_violations v
              ON v.check_name = 'local_amount_imbalance'
             AND v.company_code = s.company_code
             AND v.document_id = s.document_id
             AND v.fiscal_year = s.fiscal_year
             AND v.fiscal_period = s.fiscal_period
            WHERE {scope_s}
            GROUP BY 1, 2, 3, 4
        ),
        excluded_unbalanced AS (
            SELECT s.company_code, s.gl_account, s.fiscal_year, s.fiscal_period,
                   COUNT(DISTINCT s.document_id) AS excluded_unbalanced_doc_count
            FROM stg_gl s
            JOIN dq_violations v
              ON v.check_name = 'unbalanced_document'
             AND v.company_code = s.company_code
             AND v.document_id = s.document_id
             AND v.fiscal_year = s.fiscal_year
             AND v.fiscal_period = s.fiscal_period
            WHERE {scope_s}
            GROUP BY 1, 2, 3, 4
        )
        SELECT
            stg.company_code, stg.gl_account, stg.fiscal_year, stg.fiscal_period,
            stg.stg_debit_total, stg.stg_credit_total,
            ROUND(stg.stg_debit_total - stg.stg_credit_total, 2) AS dc_gap,
            stg.stg_local_total,
            COALESCE(fact.fact_local_total, 0) AS fact_local_total,
            ROUND(stg.stg_local_total - COALESCE(fact.fact_local_total, 0), 2) AS local_amount_gap,
            COALESCE(imbalanced.imbalanced_doc_count, 0) AS imbalanced_doc_count,
            COALESCE(imbalanced.imbalanced_local_amount, 0) AS imbalanced_local_amount,
            COALESCE(excluded_unbalanced.excluded_unbalanced_doc_count, 0) AS excluded_unbalanced_doc_count
        FROM stg
        LEFT JOIN fact USING (company_code, gl_account, fiscal_year, fiscal_period)
        LEFT JOIN imbalanced USING (company_code, gl_account, fiscal_year, fiscal_period)
        LEFT JOIN excluded_unbalanced USING (company_code, gl_account, fiscal_year, fiscal_period)
    """)
    return con.execute(f"SELECT COUNT(*) FROM recon_period_summary WHERE {scope}").fetchone()[0]


def main() -> int:
    con = duckdb.connect(str(WAREHOUSE_DB))
    periods = None
    if len(sys.argv) > 1:
        vals = [int(v) for v in sys.argv[1:]]
        if len(vals) % 3 != 0:
            print("usage: python src/reconcile_account.py [<company_code> <fiscal_year> <fiscal_period> ...]")
            return 1
        periods = [tuple(vals[i:i + 3]) for i in range(0, len(vals), 3)]
    n = build_recon_period_summary(con, periods)
    con.close()
    label = periods if periods is not None else "all periods currently in fact_gl_line"
    print(f"recon_period_summary: {n} rows for {label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
