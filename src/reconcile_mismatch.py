"""Document-level reconciliation with bucket + cause. Ticket 8,
parameterized by period in ticket 10.

Builds recon_mismatch: stg_gl vs the close-eligible subset of
fact_gl_line (excludes is_opening_balance / is_closing_entry /
is_post_close rows - comparing against the full table would only ever
produce missing_in_fact, since those flags load a row rather than
excluding it).

Bucket assignment:
  - missing_in_fact: in stg_gl, absent from fact_gl_line. Cause comes
    from the dq_violations check that rejected it.
  - intentionally_excluded: present in fact_gl_line but flagged out of
    the close-eligible view. Cause is whichever flag is set.
  - amount_changed: present in both, close-eligible, local_amount
    differs by more than 0.01.
  - missing_in_stg: in fact_gl_line, absent from stg_gl. Should never
    happen; kept as a guard.
  - matched: not written as a row. Present in both, gap within 0.01.

reversal_pair is not a bucket here - a reversal pair whose stg_gl and
fact_gl_line agree is matched, full stop. pair_id / is_swap_valid attach
to a matching row as informational attributes only, never changing its
bucket or cause.

A missing_in_fact line can have more than one dq_violations finding
against it (mission 19: e.g. its whole document is unbalanced and the
line itself is a physical duplicate). Every finding still gets logged in
dq_violations - none of them are dropped there. This file only ever picks
one as recon_mismatch's cause: document-grain blocking beats line-grain
blocking beats non-blocking, because the document-grain reason is the
real reason every line of that document is missing, not whatever else is
also wrong with one particular line. See CAUSE_RANK_SQL below.

Rebuild modes match reconcile_account.py: an explicit period list
rewrites only those periods, no args rewrites every period currently in
fact_gl_line, never a bare DELETE/CREATE OR REPLACE on the full table.

Run: python src/reconcile_mismatch.py [<company_code> <fiscal_year> <fiscal_period> ...]
  no args: rebuild for every period currently in fact_gl_line
  with args: rebuild only the given (company, year, period) triples
"""

import sys
from typing import List, Optional, Tuple

import duckdb  # type: ignore

from config import WAREHOUSE_DB
from quality_gate import CHECK_NAMES

Period = Tuple[int, int, int]

# mission 19: tie-break order when more than one dq_violations check_name
# is a candidate cause for the same recon_mismatch row, reusing the order
# quality_gate.py already declares its checks in rather than inventing a
# second one. That tuple already runs blocking checks before non-blocking
# ones and puts the one document-grain blocking check (unbalanced_document)
# first, so it doubles as the tier order build_recon_mismatch needs.
CAUSE_RANK_SQL = " ".join(f"WHEN '{name}' THEN {i}" for i, name in enumerate(CHECK_NAMES))


def all_loaded_periods(con) -> List[Period]:
    rows = con.execute("""
        SELECT DISTINCT company_code, fiscal_year, fiscal_period FROM fact_gl_line ORDER BY 1, 2, 3
    """).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def _periods_sql(periods: List[Period], alias: str = "") -> str:
    """Always returns a single, self-contained parenthesized expression,
    e.g. "((p1) OR (p2))" - callers that append " AND ..." to this in the
    same WHERE clause must not have the AND silently bind to only the
    last OR-ed period (SQL's AND binds tighter than OR). This exact bug
    hit f_close_eligible below on the first multi-period run: "WHERE
    {scope} AND NOT is_opening_balance..." only applied the NOT
    conditions to the last period before this fix."""
    prefix = f"{alias}." if alias else ""
    clauses = " OR ".join(
        f"({prefix}company_code = {c} AND {prefix}fiscal_year = {y} AND {prefix}fiscal_period = {p})"
        for c, y, p in periods
    )
    return f"({clauses})"


def ensure_table(con) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS recon_mismatch (
            company_code BIGINT, document_id VARCHAR, line_number BIGINT,
            fiscal_year BIGINT, fiscal_period BIGINT,
            bucket VARCHAR, cause VARCHAR, gap DOUBLE,
            pair_id VARCHAR, is_swap_valid BOOLEAN
        )
    """)


def build_recon_mismatch(con, periods: Optional[List[Period]] = None) -> int:
    ensure_table(con)
    if periods is None:
        periods = all_loaded_periods(con)
    if not periods:
        return 0

    scope = _periods_sql(periods)

    con.execute(f"DELETE FROM recon_mismatch WHERE {scope}")

    con.execute(f"""
        INSERT INTO recon_mismatch
        WITH s AS (
            SELECT * FROM stg_gl WHERE {scope}
        ),
        f_full AS (
            SELECT * FROM fact_gl_line WHERE {scope}
        ),
        f_close_eligible AS (
            SELECT * FROM fact_gl_line
            WHERE {scope} AND NOT is_opening_balance AND NOT is_closing_entry AND NOT is_post_close
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
        ),
        cause_pick AS (
            SELECT
                c.company_code, c.document_id, c.line_number, c.fiscal_year, c.fiscal_period,
                c.bucket, c.gap,
                COALESCE(c.cause, v.check_name) AS cause
            FROM classified c
            LEFT JOIN (
                SELECT company_code, document_id, line_number, fiscal_year, fiscal_period,
                       check_name, blocking
                FROM dq_violations
            ) v
                ON v.company_code = c.company_code AND v.document_id = c.document_id
               AND v.fiscal_year = c.fiscal_year AND v.fiscal_period = c.fiscal_period
               AND (v.line_number IS NULL OR v.line_number = c.line_number)
            -- mission 19: more than one blocking check can apply to the
            -- same line (a document-wide unbalanced_document plus a
            -- line-grain duplicate_source, say), and the join above
            -- matches every one of them - one candidate row per match.
            -- QUALIFY collapses back to the single row per source line
            -- recon_mismatch is supposed to have, keeping the highest-
            -- priority candidate: blocking + document-grain
            -- (line_number IS NULL) beats blocking + line-grain beats
            -- non-blocking. The document-grain reason is the true reason
            -- every line of that document is missing from fact_gl_line,
            -- not whatever else also happens to be wrong with one
            -- particular line. Ties inside a tier break by CAUSE_RANK_SQL
            -- (quality_gate.CHECK_NAMES' own declared order).
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY c.company_code, c.document_id, c.line_number, c.fiscal_year, c.fiscal_period
                ORDER BY
                    CASE WHEN v.blocking AND v.line_number IS NULL THEN 0
                         WHEN v.blocking THEN 1
                         WHEN v.check_name IS NOT NULL THEN 2
                         ELSE 3
                    END,
                    CASE v.check_name {CAUSE_RANK_SQL} ELSE 99 END
            ) = 1
        )
        SELECT
            cp.company_code, cp.document_id, cp.line_number, cp.fiscal_year, cp.fiscal_period,
            cp.bucket, cp.cause, cp.gap,
            p.pair_id, p.is_swap_valid
        FROM cause_pick cp
        LEFT JOIN (
            SELECT original_document_id AS document_id, original_document_id || '_' || reversal_document_id AS pair_id, is_net_zero AS is_swap_valid
            FROM recon_reversal_pairs
            UNION ALL
            SELECT reversal_document_id AS document_id, original_document_id || '_' || reversal_document_id AS pair_id, is_net_zero AS is_swap_valid
            FROM recon_reversal_pairs
        ) p ON p.document_id = cp.document_id
        WHERE cp.bucket != 'matched'
    """)
    return con.execute(f"SELECT COUNT(*) FROM recon_mismatch WHERE {scope}").fetchone()[0]


def main() -> int:
    con = duckdb.connect(str(WAREHOUSE_DB))
    periods = None
    if len(sys.argv) > 1:
        vals = [int(v) for v in sys.argv[1:]]
        if len(vals) % 3 != 0:
            print("usage: python src/reconcile_mismatch.py [<company_code> <fiscal_year> <fiscal_period> ...]")
            return 1
        periods = [tuple(vals[i:i + 3]) for i in range(0, len(vals), 3)]

    n = build_recon_mismatch(con, periods)
    scope_periods = periods if periods is not None else all_loaded_periods(con)
    scope = _periods_sql(scope_periods) if scope_periods else "1=0"
    by_bucket = con.execute(f"SELECT bucket, COUNT(*) FROM recon_mismatch WHERE {scope} GROUP BY 1 ORDER BY 1").fetchall()
    by_cause = con.execute(f"SELECT cause, COUNT(*) FROM recon_mismatch WHERE {scope} GROUP BY 1 ORDER BY 1").fetchall()
    unknown_pct = con.execute(f"""
        SELECT ROUND(100.0 * SUM((cause = 'unknown')::int) / COUNT(*), 1) FROM recon_mismatch WHERE {scope}
    """).fetchone()[0]
    con.close()

    print(f"recon_mismatch: {n} rows")
    print(f"  by bucket: {by_bucket}")
    print(f"  by cause:  {by_cause}")
    print(f"  unknown:   {unknown_pct or 0.0}% (must stay under 20%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
