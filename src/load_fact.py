"""Idempotent period loader. Ticket 4 / Mission 04, gated by Ticket 5 /
Mission 05.

Loads stg_gl -> fact_gl_line for one company + period. Replaces the whole
period every run: delete this period's rows, re-insert, one transaction.
Two runs back to back give the same row count, distinct document count,
and SUM(local_amount).

Every row is checked by src/quality_gate.py before this insert runs.
Blocking findings (unbalanced_document, duplicate_source, map_fanout,
null_key_column, unmapped_doc_type) never reach fact_gl_line; the reason
is in dq_violations, not silently dropped. Non-blocking findings
(local_amount_imbalance, unmapped_account, catch_all_account) still load
normally, just get logged alongside.

What stays in fact_gl_line but flagged, not excluded:
  - is_opening_balance / is_closing_entry: real rows, just not part of
    the in-period close total (docs/business-rules.md)

Run: python src/load_fact.py
"""

import sys

import duckdb  # type: ignore

from config import REPO_ROOT, WAREHOUSE_DB
from quality_gate import OPENING_BALANCE_TYPE, CLOSING_ENTRY_TYPE, run_gate

COMPANY_CODE = 1000
FISCAL_YEAR = 2024
FISCAL_PERIOD = 1

MAP_CSV = REPO_ROOT / "map_account.csv"

PERIOD_FILTER = (
    f"company_code = {COMPANY_CODE} AND fiscal_year = {FISCAL_YEAR} "
    f"AND fiscal_period = {FISCAL_PERIOD}"
)


def load_map_account(con) -> None:
    """map_account.csv as a real table, refreshed every run, same pattern
    as stg_gl being refreshed from parquet every run of load_stg.py."""
    con.execute(f"""
        CREATE OR REPLACE TABLE map_account AS
        SELECT * FROM read_csv_auto('{MAP_CSV}', header=true)
    """)


def ensure_tables(con) -> None:
    """Create fact_gl_line once. Later runs only delete and re-insert this
    period's slice, never recreate the table - other periods' rows (once
    #10 backfills them) must survive a P01 run. fact_gl_line_rejected
    (ticket 4's placeholder) is dropped here: dq_violations, owned by
    src/quality_gate.py, replaces it."""
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


def verify_rollback_safety(con) -> None:
    """Prove a failure mid-transaction leaves the prior period state
    exactly as it was, by deliberately breaking one and checking nothing
    changed. Runs before the real load, against whatever state is already
    there (including none, on a first run)."""
    before = con.execute(
        f"SELECT COUNT(*) FROM fact_gl_line WHERE {PERIOD_FILTER}"
    ).fetchone()[0]
    try:
        con.execute("BEGIN TRANSACTION")
        con.execute(f"DELETE FROM fact_gl_line WHERE {PERIOD_FILTER}")
        con.execute("SELECT * FROM this_table_does_not_exist")  # deliberate failure
        con.execute("COMMIT")
    except duckdb.Error:
        con.execute("ROLLBACK")
    after = con.execute(
        f"SELECT COUNT(*) FROM fact_gl_line WHERE {PERIOD_FILTER}"
    ).fetchone()[0]
    if before != after:
        print(f"BLOCKED: rollback safety check failed, before={before} after={after}")
        sys.exit(1)
    print(f"verified: a failed mid-transaction load leaves the period intact ({before} rows unchanged)")


def load_period(con) -> dict:
    con.execute("BEGIN TRANSACTION")
    try:
        gate_counts = run_gate(con, PERIOD_FILTER)

        con.execute(f"DELETE FROM fact_gl_line WHERE {PERIOD_FILTER}")

        con.execute(f"""
            INSERT INTO fact_gl_line
            SELECT s.*,
                   m.target_account, m.status AS map_status,
                   s.document_type = '{OPENING_BALANCE_TYPE}' AS is_opening_balance,
                   s.document_type = '{CLOSING_ENTRY_TYPE}' AS is_closing_entry,
                   now() AS loaded_at
            FROM stg_gl s
            LEFT JOIN map_account m ON m.source_account = s.gl_account
            WHERE {PERIOD_FILTER}
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
        FROM fact_gl_line WHERE {PERIOD_FILTER}
    """).fetchone()
    return {
        "rows": rows, "documents": docs, "sum_local_amount": total,
        "dq_violations": gate_counts,
    }


def main() -> int:
    con = duckdb.connect(str(WAREHOUSE_DB))
    load_map_account(con)
    ensure_tables(con)
    verify_rollback_safety(con)
    result = load_period(con)
    con.close()

    print(
        f"fact_gl_line ({COMPANY_CODE}, {FISCAL_YEAR}-{FISCAL_PERIOD:02d}): "
        f"{result['rows']:,} rows, {result['documents']:,} documents, "
        f"SUM(local_amount)={result['sum_local_amount']:,.2f}"
    )
    print("dq_violations:")
    for name, count in result["dq_violations"].items():
        print(f"  {name:<24} {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
