"""Reversal-pair detection. Ticket 7 / Mission 07.

Detects reversal documents by text convention and links each to its
original. No status column exists for this (ADR-0004): reference starts
'REV-<uuid>', header_text reads "Reversal of <uuid>". This rule breaks if
that wording changes upstream - if reversal counts drop to zero after a
data refresh, check the convention before assuming there are no
reversals that period (ADR-0004).

Scope: company 1000, FY2024, any pair where the original OR the reversal
falls in P01-P03 (mission 06's mapping scope). Not tied to fact_gl_line,
which only covers P01 so far - this reads stg_gl directly. A pair stays
in scope even when its other side lands outside P01-P03 (mission 07's
exploration found 126 such pairs, original in scope, reversal in P04);
narrowing to "both sides in scope" would silently drop the reversal side
of a real pair.

is_net_zero is decided on debit_amount/credit_amount, not local_amount.
Every document, original or reversal, already sums its own local_amount
to ~0 by construction (debit lines positive, credit lines negative,
cancelling within that one document) - comparing two already-zero
document totals proves nothing about whether a reversal actually offsets
its original. The real signal is whether debit and credit SWAP between
the two documents (original's debit total equals the reversal's credit
total, and vice versa). local_amount carries a second, separate defect
on reversal documents: it is copied verbatim from the original instead
of being re-signed, so for a textbook-valid pair, summing local_amount
per account doubles the figure instead of cancelling it. The raw
local_amount columns are kept here for visibility, not as the net-zero
signal.

is_swap_valid is false for 85 of 1025 pairs in this scope: the text
convention matches (real REV- reference, real "Reversal of <id>" wording)
but the amounts and line counts don't correspond to the claimed original
at all. 83 of those 85 carry an is_fraud or is_anomaly flag - this reads
as a planted fake-reversal anomaly, not a real reversal gone wrong. Kept
as a row, flagged, never filtered (ADR-0003): the text convention
matched, so ADR-0004's detection rule says this is a reversal pair.
Whether it's economically valid is a different question, answered by
is_swap_valid, not by omission from this table.

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
            ABS(o.debit_total - v.credit_total) <= {SWAP_TOLERANCE}
                AND ABS(o.credit_total - v.debit_total) <= {SWAP_TOLERANCE} AS is_net_zero,
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
