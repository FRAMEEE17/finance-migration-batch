"""Idempotent period loader. Ticket 4, gated by ticket 5, parameterized
by period in ticket 10.

Loads stg_gl -> fact_gl_line for one company + period(s), one delete +
insert transaction per period. No default period: a bare call fails
with a usage message rather than silently loading one.

Run: python src/load_fact.py <company_code> <fiscal_year> <fiscal_period> [<fiscal_period> ...]
  e.g. python src/load_fact.py 1000 2024 1 2 3
"""

import sys

import duckdb  # type: ignore

from config import REPO_ROOT, WAREHOUSE_DB
from quality_gate import OPENING_BALANCE_TYPE, CLOSING_ENTRY_TYPE, run_gate

MAP_CSV = REPO_ROOT / "map_account.csv"


def period_filter(company_code: int, fiscal_year: int, fiscal_period: int) -> str:
    return (
        f"company_code = {company_code} AND fiscal_year = {fiscal_year} "
        f"AND fiscal_period = {fiscal_period}"
    )


def load_map_account(con) -> None:
    """map_account.csv as a real table, refreshed every run, same pattern
    as stg_gl being refreshed from parquet every run of load_stg.py."""
    con.execute(f"""
        CREATE OR REPLACE TABLE map_account AS
        SELECT * FROM read_csv_auto('{MAP_CSV}', header=true)
    """)


def ensure_tables(con) -> None:
    """Create fact_gl_line once. Later runs only delete and re-insert the
    period being loaded, never recreate the table - other periods'
    already-loaded rows must survive a run for a different period.
    fact_gl_line_rejected (ticket 4's placeholder) is dropped here:
    dq_violations, owned by src/quality_gate.py, replaces it."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS fact_gl_line AS
        SELECT s.*,
               NULL::VARCHAR AS target_account,
               NULL::VARCHAR AS map_status,
               false AS is_opening_balance,
               false AS is_closing_entry,
               NULL::TIMESTAMP AS loaded_at
        FROM stg_gl s WHERE 1 = 0
    """)
    con.execute("DROP TABLE IF EXISTS fact_gl_line_rejected")


def verify_rollback_safety(con, company_code: int, fiscal_year: int, fiscal_period: int) -> None:
    """Prove a failure mid-transaction leaves the prior period state
    exactly as it was, by deliberately breaking one and checking nothing
    changed. Runs before the real load, against whatever state is already
    there (including none, on a first run)."""
    pf = period_filter(company_code, fiscal_year, fiscal_period)
    before = con.execute(f"SELECT COUNT(*) FROM fact_gl_line WHERE {pf}").fetchone()[0]
    try:
        con.execute("BEGIN TRANSACTION")
        con.execute(f"DELETE FROM fact_gl_line WHERE {pf}")
        con.execute("SELECT * FROM this_table_does_not_exist")  # deliberate failure
        con.execute("COMMIT")
    except duckdb.Error:
        con.execute("ROLLBACK")
    after = con.execute(f"SELECT COUNT(*) FROM fact_gl_line WHERE {pf}").fetchone()[0]
    if before != after:
        print(f"BLOCKED: rollback safety check failed, before={before} after={after}")
        sys.exit(1)
    print(f"verified: a failed mid-transaction load leaves {fiscal_year}-{fiscal_period:02d} intact ({before} rows unchanged)")


def load_period(con, company_code: int, fiscal_year: int, fiscal_period: int) -> dict:
    pf = period_filter(company_code, fiscal_year, fiscal_period)

    con.execute("BEGIN TRANSACTION")
    try:
        gate_counts = run_gate(con, pf)

        con.execute(f"DELETE FROM fact_gl_line WHERE {pf}")

        con.execute(f"""
            INSERT INTO fact_gl_line
            SELECT s.*,
                   m.target_account, m.status AS map_status,
                   s.document_type = '{OPENING_BALANCE_TYPE}' AS is_opening_balance,
                   s.document_type = '{CLOSING_ENTRY_TYPE}' AS is_closing_entry,
                   now() AS loaded_at
            FROM stg_gl s
            LEFT JOIN map_account m ON m.source_account = s.gl_account
            WHERE {pf}
              -- only blocking dq_violations exclude a row; non-blocking
              -- findings still load, just get logged alongside
              AND NOT EXISTS (
                  SELECT 1 FROM dq_violations v
                  WHERE v.blocking = true
                    AND v.company_code = s.company_code
                    AND v.document_id = s.document_id
                    AND v.fiscal_year = s.fiscal_year
                    AND v.fiscal_period = s.fiscal_period
                    AND (v.line_number IS NULL OR v.line_number = s.line_number)
              )
        """)

        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    rows, docs, total = con.execute(f"""
        SELECT COUNT(*), COUNT(DISTINCT document_id), ROUND(SUM(local_amount), 2)
        FROM fact_gl_line WHERE {pf}
    """).fetchone()
    return {
        "rows": rows, "documents": docs, "sum_local_amount": total,
        "dq_violations": gate_counts,
    }


def main() -> int:
    if len(sys.argv) < 4:
        print("usage: python src/load_fact.py <company_code> <fiscal_year> <fiscal_period> [<fiscal_period> ...]")
        print("  e.g. python src/load_fact.py 1000 2024 1 2 3")
        return 1

    company_code = int(sys.argv[1])
    fiscal_year = int(sys.argv[2])
    fiscal_periods = [int(p) for p in sys.argv[3:]]

    con = duckdb.connect(str(WAREHOUSE_DB))
    load_map_account(con)
    ensure_tables(con)

    for fiscal_period in fiscal_periods:
        verify_rollback_safety(con, company_code, fiscal_year, fiscal_period)
        result = load_period(con, company_code, fiscal_year, fiscal_period)
        print(
            f"fact_gl_line ({company_code}, {fiscal_year}-{fiscal_period:02d}): "
            f"{result['rows']:,} rows, {result['documents']:,} documents, "
            f"SUM(local_amount)={result['sum_local_amount']:,.2f}"
        )
        print("dq_violations:")
        for name, count in result["dq_violations"].items():
            print(f"  {name:<24} {count}")

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
