"""Reversal-pair detection. Ticket 7.

Detects reversal documents by text convention (ADR-0004, no status
column exists): reference starts 'REV-<uuid>', header_text reads
"Reversal of <uuid>". Scope: company 1000, FY2024, any pair where either
side falls in P01-P03 - reads stg_gl directly, not fact_gl_line, so a
pair stays in scope even when its other side doesn't (mission 07).

Run: python src/reconcile_reversals.py
"""

import sys

import duckdb  # type: ignore

from config import WAREHOUSE_DB

COMPANY_CODE = 1000
IN_SCOPE_YEAR = 2024
IN_SCOPE_PERIODS = (1, 2, 3)

SWAP_TOLERANCE = 0.01


def build_recon_reversal_pairs(con) -> int:
    periods_sql = ",".join(str(p) for p in IN_SCOPE_PERIODS)
    con.execute(f"""
        CREATE OR REPLACE TABLE recon_reversal_pairs AS
        WITH rev AS (
            -- ADR-0004: this is the whole detection rule. If this CTE
            -- ever returns 0 rows, check whether "Reversal of " or the
            -- "REV-" prefix changed upstream before assuming there are
            -- no reversals.
            SELECT DISTINCT document_id AS reversal_document_id,
                   regexp_extract(header_text, 'Reversal of (.+)', 1) AS original_document_id
            FROM stg_gl
            WHERE company_code = {COMPANY_CODE} AND reference LIKE 'REV-%'
        ),
        doc_totals AS (
            SELECT document_id, fiscal_year, fiscal_period,
                   ROUND(SUM(debit_amount), 2) AS debit_total,
                   ROUND(SUM(credit_amount), 2) AS credit_total,
                   ROUND(SUM(local_amount), 2) AS local_total,
                   bool_or(is_fraud) AS any_fraud,
                   bool_or(is_anomaly) AS any_anomaly
            FROM stg_gl
            WHERE company_code = {COMPANY_CODE}
            GROUP BY 1, 2, 3
        )
        SELECT
            r.original_document_id, r.reversal_document_id,
            o.fiscal_year AS original_fiscal_year, o.fiscal_period AS original_fiscal_period,
            v.fiscal_year AS reversal_fiscal_year, v.fiscal_period AS reversal_fiscal_period,
            (o.fiscal_year != v.fiscal_year OR o.fiscal_period != v.fiscal_period) AS cross_period,
            o.debit_total AS original_debit_total, o.credit_total AS original_credit_total,
            v.debit_total AS reversal_debit_total, v.credit_total AS reversal_credit_total,
            -- Decided on debit/credit swapping between the two documents,
            -- not local_amount: every document already sums its own
            -- local_amount to ~0 by construction, so comparing two
            -- already-zero totals proves nothing about a real reversal.
            ABS(o.debit_total - v.credit_total) <= {SWAP_TOLERANCE}
                AND ABS(o.credit_total - v.debit_total) <= {SWAP_TOLERANCE} AS is_net_zero,
            -- local_amount is copied verbatim onto the reversal instead of
            -- re-signed, so summing it per account doubles a valid pair's
            -- figure instead of cancelling it. Kept for visibility only.
            o.local_total AS original_local_amount, v.local_total AS reversal_local_amount,
            ROUND(o.local_total + v.local_total, 2) AS net_local_amount,
            (o.any_fraud OR o.any_anomaly OR v.any_fraud OR v.any_anomaly) AS any_flagged
        FROM rev r
        JOIN doc_totals o ON o.document_id = r.original_document_id
        JOIN doc_totals v ON v.document_id = r.reversal_document_id
        WHERE (o.fiscal_year = {IN_SCOPE_YEAR} AND o.fiscal_period IN ({periods_sql}))
           OR (v.fiscal_year = {IN_SCOPE_YEAR} AND v.fiscal_period IN ({periods_sql}))
    """)
    return con.execute("SELECT COUNT(*) FROM recon_reversal_pairs").fetchone()[0]


def main() -> int:
    con = duckdb.connect(str(WAREHOUSE_DB))
    n = build_recon_reversal_pairs(con)
    stats = con.execute("""
        SELECT COUNT(*), SUM(cross_period::int),
               SUM(is_net_zero::int), SUM((NOT is_net_zero)::int),
               SUM(CASE WHEN NOT is_net_zero AND any_flagged THEN 1 ELSE 0 END)
        FROM recon_reversal_pairs
    """).fetchone()
    con.close()

    total, cross_period, valid, invalid, invalid_flagged = stats
    print(f"recon_reversal_pairs: {total} pairs, {cross_period} cross-period")
    print(f"  is_net_zero=true (valid swap):   {valid}")
    print(f"  is_net_zero=false (not a real reversal): {invalid} ({invalid_flagged} of those flagged fraud/anomaly)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
