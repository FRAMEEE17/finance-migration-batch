"""Document-level reconciliation with bucket + cause. Ticket 8 / Mission 08.

Builds recon_mismatch: one row per grain-level difference between stg_gl
and the close-eligible subset of fact_gl_line (excludes rows flagged
is_opening_balance / is_closing_entry / is_post_close - the ones
business-rules.md says are "never mixed into in-period totals"). A plain
row-for-row join against the full fact_gl_line table only ever produces
missing_in_fact, since those three flags load and flag a row rather than
excluding it from the table (mission 04's decision); comparing against
the close-eligible subset instead is what gives every bucket real
content (mission 08's Exploration).

Bucket assignment:
  - missing_in_fact: in stg_gl, absent from fact_gl_line entirely (not
    just excluded from the close-eligible view). Cause comes from
    dq_violations (the blocking check that rejected it).
  - intentionally_excluded: in stg_gl, present in fact_gl_line, but
    flagged out of the close-eligible view. Cause is whichever flag is
    set (opening_balance / closing_entry / post_close).
  - amount_changed: present in both, close-eligible, but local_amount
    differs by more than 0.01. No real case in P01; the bucket logic is
    built and proven with a synthetic row, cause-assignment logic for it
    is not (see mission 08's Non-goals).
  - missing_in_stg: in fact_gl_line, absent from stg_gl. Should never
    happen (fact_gl_line is built as a filtered subset of stg_gl); kept
    as a guard, not expected to ever hold a row.
  - matched (not a mismatch, no row in recon_mismatch): present in both,
    close-eligible, gap within 0.01.

reversal_pair is not a bucket this mission assigns. A reversal pair
whose stg_gl and fact_gl_line agree is matched, full stop - #8 answers
why a row doesn't compare equal in the close-eligible set, not what a
transaction means economically. pair_id / is_swap_valid are attached to
every recon_mismatch row as informational attributes (nullable, from
recon_reversal_pairs) so a reader can see a mismatched row is also part
of a detected pair, without that fact changing its bucket or cause.

Run: python src/reconcile_mismatch.py
"""

import sys

import duckdb  # type: ignore

from config import WAREHOUSE_DB
from load_fact import PERIOD_FILTER


def build_recon_mismatch(con) -> int:
    con.execute(f"""
        CREATE OR REPLACE TABLE recon_mismatch AS
        WITH s AS (
            SELECT * FROM stg_gl WHERE {PERIOD_FILTER}
        ),
        f_full AS (
            SELECT * FROM fact_gl_line
        ),
        f_close_eligible AS (
            SELECT * FROM fact_gl_line
            WHERE NOT is_opening_balance AND NOT is_closing_entry AND NOT is_post_close
        ),
        joined AS (
            SELECT
                COALESCE(s.company_code, ff.company_code) AS company_code,
                COALESCE(s.document_id, ff.document_id) AS document_id,
                COALESCE(s.line_number, ff.line_number) AS line_number,
                COALESCE(s.fiscal_year, ff.fiscal_year) AS fiscal_year,
                COALESCE(s.fiscal_period, ff.fiscal_period) AS fiscal_period,
                s.document_id IS NOT NULL AS in_stg,
                fce.document_id IS NOT NULL AS in_fact_close_eligible,
                ff.document_id IS NOT NULL AS in_fact_full,
                ff.is_opening_balance, ff.is_closing_entry, ff.is_post_close,
                ROUND(COALESCE(s.local_amount, 0) - COALESCE(fce.local_amount, 0), 2) AS gap
            FROM s
            FULL OUTER JOIN f_close_eligible fce
                USING (company_code, document_id, line_number, fiscal_year, fiscal_period)
            LEFT JOIN f_full ff
                USING (company_code, document_id, line_number, fiscal_year, fiscal_period)
        ),
        classified AS (
            SELECT company_code, document_id, line_number, fiscal_year, fiscal_period, gap,
                CASE
                    WHEN NOT in_stg THEN 'missing_in_stg'
                    WHEN NOT in_fact_full THEN 'missing_in_fact'
                    WHEN NOT in_fact_close_eligible THEN 'intentionally_excluded'
                    WHEN ABS(gap) > 0.01 THEN 'amount_changed'
                    ELSE 'matched'
                END AS bucket,
                CASE
                    WHEN NOT in_stg THEN 'unknown'
                    WHEN NOT in_fact_full THEN NULL  -- filled from dq_violations below
                    WHEN NOT in_fact_close_eligible AND is_opening_balance THEN 'opening_balance'
                    WHEN NOT in_fact_close_eligible AND is_closing_entry THEN 'closing_entry'
                    WHEN NOT in_fact_close_eligible AND is_post_close THEN 'post_close'
                    WHEN ABS(gap) > 0.01 THEN 'unknown'  -- no real case yet to derive a cause from, see mission 08
                    ELSE NULL
                END AS cause
            FROM joined
        )
        SELECT
            c.company_code, c.document_id, c.line_number, c.fiscal_year, c.fiscal_period,
            c.bucket,
            COALESCE(c.cause, v.check_name) AS cause,
            c.gap,
            p.pair_id, p.is_swap_valid
        FROM classified c
        LEFT JOIN (
            SELECT company_code, document_id, line_number, fiscal_year, fiscal_period, check_name
            FROM dq_violations WHERE blocking = true
        ) v
            ON v.company_code = c.company_code AND v.document_id = c.document_id
           AND v.fiscal_year = c.fiscal_year AND v.fiscal_period = c.fiscal_period
           AND (v.line_number IS NULL OR v.line_number = c.line_number)
        LEFT JOIN (
            SELECT original_document_id AS document_id, original_document_id || '_' || reversal_document_id AS pair_id, is_net_zero AS is_swap_valid
            FROM recon_reversal_pairs
            UNION ALL
            SELECT reversal_document_id AS document_id, original_document_id || '_' || reversal_document_id AS pair_id, is_net_zero AS is_swap_valid
            FROM recon_reversal_pairs
        ) p ON p.document_id = c.document_id
        WHERE c.bucket != 'matched'
    """)
    return con.execute("SELECT COUNT(*) FROM recon_mismatch").fetchone()[0]


def main() -> int:
    con = duckdb.connect(str(WAREHOUSE_DB))
    n = build_recon_mismatch(con)
    by_bucket = con.execute("SELECT bucket, COUNT(*) FROM recon_mismatch GROUP BY 1 ORDER BY 1").fetchall()
    by_cause = con.execute("SELECT cause, COUNT(*) FROM recon_mismatch GROUP BY 1 ORDER BY 1").fetchall()
    unknown_pct = con.execute("""
        SELECT ROUND(100.0 * SUM((cause = 'unknown')::int) / COUNT(*), 1) FROM recon_mismatch
    """).fetchone()[0]
    con.close()

    print(f"recon_mismatch: {n} rows")
    print(f"  by bucket: {by_bucket}")
    print(f"  by cause:  {by_cause}")
    print(f"  unknown:   {unknown_pct or 0.0}% (must stay under 20%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
