"""Idempotent period loader. Ticket 4 / Mission 04.

Loads stg_gl -> fact_gl_line for one company + period. Replaces the whole
period every run: delete this period's rows, re-insert, one transaction.
Two runs back to back give the same row count, distinct document count,
and SUM(local_amount).

What gets excluded entirely (never lands in fact_gl_line, goes to
fact_gl_line_rejected instead):
  - unbalanced_document: the whole document, every line, not just the
    line that doesn't balance (docs/business-rules.md)
  - unmapped_doc_type: a document_type outside the known catalog

What stays in fact_gl_line but flagged, not excluded:
  - is_opening_balance / is_closing_entry: real rows, just not part of
    the in-period close total (docs/business-rules.md)

Run: python src/load_fact.py
"""

import sys

import duckdb  # type: ignore

from config import REPO_ROOT, WAREHOUSE_DB

COMPANY_CODE = 1000
FISCAL_YEAR = 2024
FISCAL_PERIOD = 1

MAP_CSV = REPO_ROOT / "map_account.csv"

# docs/business-rules.md doc_type catalog
COUNTED_DOC_TYPES = {"SA", "DR", "KR", "DZ", "KZ", "AA", "WE", "WL", "HR", "IC"}
OPENING_BALANCE_TYPE = "OPENING_BALANCE"
CLOSING_ENTRY_TYPE = "CL"
KNOWN_DOC_TYPES = COUNTED_DOC_TYPES | {OPENING_BALANCE_TYPE, CLOSING_ENTRY_TYPE}

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
    """Create fact_gl_line / fact_gl_line_rejected once. Later runs only
    delete and re-insert this period's slice, never recreate the table -
    other periods' rows (once #10 backfills them) must survive a P01 run."""
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
    con.execute("""
        CREATE TABLE IF NOT EXISTS fact_gl_line_rejected AS
        SELECT company_code, document_id, line_number, fiscal_year, fiscal_period,
               document_type,
               ''::VARCHAR AS reject_reason,
               NULL::TIMESTAMP AS rejected_at
        FROM stg_gl WHERE 1 = 0
    """)


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
    known_types_sql = ",".join(f"'{t}'" for t in KNOWN_DOC_TYPES)

    unbalanced_docs = con.execute(f"""
        SELECT document_id FROM stg_gl WHERE {PERIOD_FILTER}
        GROUP BY 1 HAVING ROUND(SUM(debit_amount) - SUM(credit_amount), 2) != 0
    """).fetchall()
    unbalanced_ids = [r[0] for r in unbalanced_docs]
    unbalanced_sql = ",".join(f"'{d}'" for d in unbalanced_ids) if unbalanced_ids else "NULL"

    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(f"DELETE FROM fact_gl_line WHERE {PERIOD_FILTER}")
        con.execute(f"DELETE FROM fact_gl_line_rejected WHERE {PERIOD_FILTER}")

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
              AND s.document_type IN ({known_types_sql})
              AND s.document_id NOT IN ({unbalanced_sql})
        """)

        con.execute(f"""
            INSERT INTO fact_gl_line_rejected
            SELECT company_code, document_id, line_number, fiscal_year, fiscal_period,
                   document_type,
                   CASE WHEN document_type NOT IN ({known_types_sql}) THEN 'unmapped_doc_type'
                        ELSE 'unbalanced_document' END,
                   now()
            FROM stg_gl
            WHERE {PERIOD_FILTER}
              AND (document_type NOT IN ({known_types_sql}) OR document_id IN ({unbalanced_sql}))
        """)

        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    rows, docs, total = con.execute(f"""
        SELECT COUNT(*), COUNT(DISTINCT document_id), ROUND(SUM(local_amount), 2)
        FROM fact_gl_line WHERE {PERIOD_FILTER}
    """).fetchone()
    rejected = con.execute(f"""
        SELECT reject_reason, COUNT(*) FROM fact_gl_line_rejected
        WHERE {PERIOD_FILTER} GROUP BY 1
    """).fetchall()
    return {"rows": rows, "documents": docs, "sum_local_amount": total, "rejected": dict(rejected)}


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
    print(f"rejected: {result['rejected'] or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
