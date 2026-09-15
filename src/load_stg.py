"""Load the raw journal entries into stg_gl, as-is.

Ticket 2. stg_gl is a faithful copy of the source file: no renames, no casts,
no filtering, all companies, all periods. It is the left side of every
reconciliation, so it has to match the source exactly.

Run: python src/load_stg.py
"""

import sys

import duckdb # type: ignore

from config import SOURCE_PARQUET, WAREHOUSE_DB

SOURCE = str(SOURCE_PARQUET)


def _schema(con: duckdb.DuckDBPyConnection, relation: str) -> list[tuple[str, str]]:
    rows = con.execute(f"DESCRIBE {relation}").fetchall()
    return [(r[0], r[1]) for r in rows]


def main(warehouse_db=None) -> int:
    """warehouse_db overrides WAREHOUSE_DB for one call - mission 21's
    recovery demo (issue #25) needs the DAG to point a single run at a
    throwaway warehouse copy, and unlike every other task's own
    duckdb.connect() call, this script had no way to take that override
    except the env var, which is baked into WAREHOUSE_DB at import time
    (too early for a per-run demo param to reach). Every other caller
    passes nothing and gets the exact behavior this always had."""
    con = duckdb.connect(str(warehouse_db or WAREHOUSE_DB))

    src_rel = f"(SELECT * FROM read_parquet('{SOURCE}'))"
    expected_rows = con.execute(f"SELECT COUNT(*) FROM {src_rel}").fetchone()[0]
    src_schema = _schema(con, f"SELECT * FROM read_parquet('{SOURCE}')")

    con.execute(
        f"CREATE OR REPLACE TABLE stg_gl AS SELECT * FROM read_parquet('{SOURCE}')"
    )

    rows = con.execute("SELECT COUNT(*) FROM stg_gl").fetchone()[0]
    tbl_schema = _schema(con, "stg_gl")

    ok = True
    if rows != expected_rows:
        print(f"FAIL  rows: stg_gl={rows:,}  source={expected_rows:,}")
        ok = False
    if tbl_schema != src_schema:
        print("FAIL  schema differs from source")
        for a, b in zip(src_schema, tbl_schema):
            if a != b:
                print(f"      source {a}  ->  stg_gl {b}")
        ok = False

    summary = con.execute(
        """
        SELECT COUNT(DISTINCT document_id),
               COUNT(DISTINCT company_code),
               MIN(fiscal_year), MAX(fiscal_year)
        FROM stg_gl
        """
    ).fetchone()
    print(f"stg_gl: {rows:,} rows, {len(tbl_schema)} columns")
    print(
        f"  documents: {summary[0]:,}   companies: {summary[1]}"
        f"   fiscal_year: {summary[2]}-{summary[3]}"
    )

    con.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
