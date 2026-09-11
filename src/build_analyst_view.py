"""Safe read gate for daily data consumers. Ticket 16.

Creates fact_gl_line_ready: fact_gl_line joined to period_signoff,
filtered to recon_status='accepted', with is_period_movement computed
so a consumer doesn't need to know to combine 3 flags by hand. Not a
dashboard, not a second sign-off artifact - see
docs/how-to-query-fact_gl_line.md for what this view is for.

Run: python src/build_analyst_view.py
"""

import sys

import duckdb  # type: ignore

from config import WAREHOUSE_DB


def build_fact_gl_line_ready(con) -> None:
    con.execute("""
        CREATE OR REPLACE VIEW fact_gl_line_ready AS
        SELECT
            f.*,
            ps.recon_status,
            ps.local_amount_status,
            NOT f.is_opening_balance AND NOT f.is_closing_entry AND NOT f.is_post_close
                AS is_period_movement
        FROM fact_gl_line f
        JOIN period_signoff ps
          ON ps.company_code = f.company_code
         AND ps.fiscal_year = f.fiscal_year
         AND ps.fiscal_period = f.fiscal_period
        WHERE ps.recon_status = 'accepted'
    """)


def main() -> int:
    con = duckdb.connect(str(WAREHOUSE_DB))
    build_fact_gl_line_ready(con)
    n = con.execute("SELECT COUNT(*) FROM fact_gl_line_ready").fetchone()[0]
    periods = con.execute("""
        SELECT DISTINCT fiscal_year, fiscal_period FROM fact_gl_line_ready ORDER BY 1, 2
    """).fetchall()
    con.close()
    print(f"fact_gl_line_ready: {n:,} rows across {len(periods)} ready period(s): {periods}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
