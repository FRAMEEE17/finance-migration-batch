"""Account-level reconciliation. Ticket 6 / Mission 06.

Builds recon_period_summary: one row per (gl_account, fiscal_year,
fiscal_period) in scope, comparing stg_gl to fact_gl_line. Separate
columns for the real gap (debit vs credit, which stays clean) and the
known-broken one (local_amount, per mission 06's exploration) - a single
net column would show the same 97M distortion the mission exists to
explain, not fix.

This script never touches local_amount. It reports on the defect found
in mission 06 (20 documents whose local_amount is the document total
broadcast onto every debit line, not a per-line amount); the fix, if any,
belongs to the source-data ticket that finding opened, not here.

Run: python src/reconcile_account.py
"""

import sys

import duckdb  # type: ignore

from config import WAREHOUSE_DB
from load_fact import PERIOD_FILTER, COMPANY_CODE, FISCAL_YEAR, FISCAL_PERIOD
from quality_gate import ensure_dq_violations_table

# Same scope as PERIOD_FILTER, columns qualified with s. - needed wherever
# a query joins stg_gl (alias s) against another table with the same
# column names (dq_violations), to avoid an ambiguous column error.
SCOPE_S = (
    f"s.company_code = {COMPANY_CODE} AND s.fiscal_year = {FISCAL_YEAR} "
    f"AND s.fiscal_period = {FISCAL_PERIOD}"
)


def build_recon_period_summary(con) -> int:
    ensure_dq_violations_table(con)
    con.execute(f"""
        CREATE OR REPLACE TABLE recon_period_summary AS
        WITH stg AS (
            SELECT company_code, gl_account, fiscal_year, fiscal_period,
                   ROUND(SUM(debit_amount), 2) AS stg_debit_total,
                   ROUND(SUM(credit_amount), 2) AS stg_credit_total,
                   ROUND(SUM(local_amount), 2) AS stg_local_total
            FROM stg_gl WHERE {PERIOD_FILTER}
            GROUP BY 1, 2, 3, 4
        ),
        fact AS (
            SELECT company_code, gl_account, fiscal_year, fiscal_period,
                   ROUND(SUM(local_amount), 2) AS fact_local_total
            FROM fact_gl_line
            GROUP BY 1, 2, 3, 4
        ),
        -- documents flagged local_amount_imbalance by the quality gate,
        -- attributed back to each gl_account that has a line on them
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
            WHERE {SCOPE_S}
            GROUP BY 1, 2, 3, 4
        ),
        -- documents excluded from fact_gl_line for being unbalanced,
        -- attributed back to each gl_account that has a line on them
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
            WHERE {SCOPE_S}
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
    return con.execute("SELECT COUNT(*) FROM recon_period_summary").fetchone()[0]


def main() -> int:
    con = duckdb.connect(str(WAREHOUSE_DB))
    n = build_recon_period_summary(con)
    con.close()
    print(f"recon_period_summary: {n} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
