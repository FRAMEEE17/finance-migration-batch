"""Quality gate in front of fact_gl_line. Ticket 5 / Mission 05.

Runs the blocking and non-blocking checks over one scope and logs every
finding to dq_violations. Blocking findings are what load_fact.py's
insert excludes; non-blocking findings are visibility only, never a
reason to drop a row.

Blocking (rejected rows never reach fact_gl_line):
  - unbalanced_document: a document's debit_amount - credit_amount != 0
  - duplicate_source: the same grain appears more than once in stg_gl
  - map_fanout: source_account appears more than once in map_account.csv
  - null_key_column: a null in company_code/document_id/line_number/
    fiscal_year/fiscal_period/gl_account
  - unmapped_doc_type: document_type outside the known catalog (not one
    of issue #5's 4 named checks, but fact_gl_line_rejected is retired by
    this mission and this is the reason that table used to carry)

Non-blocking (row still loads, finding just gets logged):
  - local_amount_imbalance: balances on debit/credit, local_amount doesn't
    net to zero
  - unmapped_account: status='unmapped', or status='deprecated' with no
    target_account. Never status='catch_all' - see catch_all_account
  - catch_all_account: status='catch_all' (ADR-0005)

Run standalone: python src/quality_gate.py
(also imported by src/load_fact.py, which calls run_gate() inside its
own transaction before inserting into fact_gl_line)
"""

import sys

import duckdb  # type: ignore

from config import WAREHOUSE_DB

KEY_COLUMNS = (
    "company_code", "document_id", "line_number", "fiscal_year", "fiscal_period", "gl_account",
)

CHECK_NAMES = (
    "unbalanced_document", "duplicate_source", "map_fanout", "null_key_column",
    "unmapped_doc_type", "local_amount_imbalance", "unmapped_account", "catch_all_account",
)

# docs/business-rules.md doc_type catalog, same set src/load_fact.py uses
COUNTED_DOC_TYPES = {"SA", "DR", "KR", "DZ", "KZ", "AA", "WE", "WL", "HR", "IC"}
OPENING_BALANCE_TYPE = "OPENING_BALANCE"
CLOSING_ENTRY_TYPE = "CL"
KNOWN_DOC_TYPES = COUNTED_DOC_TYPES | {OPENING_BALANCE_TYPE, CLOSING_ENTRY_TYPE}


def ensure_dq_violations_table(con) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS dq_violations (
            check_name VARCHAR,
            blocking BOOLEAN,
            company_code BIGINT,
            document_id VARCHAR,
            line_number BIGINT,
            fiscal_year BIGINT,
            fiscal_period BIGINT,
            detail VARCHAR,
            checked_at TIMESTAMP
        )
    """)


def _log(con, check_name: str, blocking: bool, findings: list[tuple]) -> int:
    """findings: list of (company_code, document_id, line_number,
    fiscal_year, fiscal_period, detail) tuples. line_number may be None
    for a check that operates at document grain."""
    if not findings:
        return 0
    con.executemany(
        """
        INSERT INTO dq_violations
        (check_name, blocking, company_code, document_id, line_number,
         fiscal_year, fiscal_period, detail, checked_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, now())
        """,
        [(check_name, blocking, *row) for row in findings],
    )
    return len(findings)


def run_gate(con, scope_filter: str) -> dict:
    """Delete this scope's prior findings, recompute all 8 checks, log
    every finding to dq_violations. Returns {check_name: count}. Blocking
    findings are read back by load_fact.py via dq_violations itself
    (blocking=true rows for this scope), not returned separately."""
    ensure_dq_violations_table(con)
    con.execute(f"DELETE FROM dq_violations WHERE {scope_filter}")

    counts = {}

    # --- blocking: unbalanced_document (document grain) --------------------
    unbalanced = con.execute(f"""
        SELECT company_code, document_id, NULL, fiscal_year, fiscal_period,
               'gap=' || ROUND(SUM(debit_amount) - SUM(credit_amount), 2) ||
               ' lines=' || COUNT(*)
        FROM stg_gl WHERE {scope_filter}
        GROUP BY 1, 2, 4, 5 HAVING ROUND(SUM(debit_amount) - SUM(credit_amount), 2) != 0
    """).fetchall()
    counts["unbalanced_document"] = _log(con, "unbalanced_document", True, unbalanced)

    # --- blocking: duplicate_source (line grain) ----------------------------
    dupes = con.execute(f"""
        SELECT company_code, document_id, line_number, fiscal_year, fiscal_period,
               'appears ' || COUNT(*) || 'x in stg_gl'
        FROM stg_gl WHERE {scope_filter}
        GROUP BY 1, 2, 3, 4, 5 HAVING COUNT(*) > 1
    """).fetchall()
    counts["duplicate_source"] = _log(con, "duplicate_source", True, dupes)

    # --- blocking: map_fanout (line grain, via gl_account) ------------------
    fanout_accounts = con.execute("""
        SELECT source_account, COUNT(*) n FROM map_account GROUP BY 1 HAVING n > 1
    """).fetchall()
    if fanout_accounts:
        acct_list = ",".join(str(a[0]) for a in fanout_accounts)
        fanout_rows = con.execute(f"""
            SELECT company_code, document_id, line_number, fiscal_year, fiscal_period,
                   'source_account ' || gl_account || ' appears >1x in map_account.csv'
            FROM stg_gl WHERE {scope_filter} AND gl_account IN ({acct_list})
        """).fetchall()
    else:
        fanout_rows = []
    counts["map_fanout"] = _log(con, "map_fanout", True, fanout_rows)

    # --- blocking: null_key_column (line grain) -----------------------------
    # COALESCE-driven detail: names the specific column(s) that are null,
    # not just that "one of the six" is.
    null_case = " || ".join(
        f"CASE WHEN {c} IS NULL THEN '{c} ' ELSE '' END" for c in KEY_COLUMNS
    )
    null_key_cond = " OR ".join(f"{c} IS NULL" for c in KEY_COLUMNS)
    nulls = con.execute(f"""
        SELECT company_code, document_id, line_number, fiscal_year, fiscal_period,
               'null in: ' || TRIM({null_case})
        FROM stg_gl WHERE {scope_filter} AND ({null_key_cond})
    """).fetchall()
    counts["null_key_column"] = _log(con, "null_key_column", True, nulls)

    # --- blocking: unmapped_doc_type (line grain) ----------------------------
    known_types_sql = ",".join(f"'{t}'" for t in KNOWN_DOC_TYPES)
    bad_types = con.execute(f"""
        SELECT company_code, document_id, line_number, fiscal_year, fiscal_period,
               'document_type=' || document_type || ' outside known catalog'
        FROM stg_gl WHERE {scope_filter} AND document_type NOT IN ({known_types_sql})
    """).fetchall()
    counts["unmapped_doc_type"] = _log(con, "unmapped_doc_type", True, bad_types)

    # --- non-blocking: local_amount_imbalance (document grain) -------------
    imbalanced = con.execute(f"""
        SELECT company_code, document_id, NULL, fiscal_year, fiscal_period,
               'local_amount nets to ' || ROUND(SUM(local_amount), 2)
        FROM stg_gl WHERE {scope_filter}
        GROUP BY 1, 2, 4, 5
        HAVING ROUND(SUM(debit_amount) - SUM(credit_amount), 2) = 0
           AND ROUND(SUM(local_amount), 2) != 0
    """).fetchall()
    counts["local_amount_imbalance"] = _log(con, "local_amount_imbalance", False, imbalanced)

    # --- non-blocking: unmapped_account (line grain) ------------------------
    unmapped_accounts = con.execute("""
        SELECT source_account FROM map_account
        WHERE status = 'unmapped' OR (status = 'deprecated' AND (target_account IS NULL OR target_account = ''))
    """).fetchall()
    unmapped_list = ",".join(str(a[0]) for a in unmapped_accounts) if unmapped_accounts else "NULL"
    unmapped_rows = con.execute(f"""
        SELECT company_code, document_id, line_number, fiscal_year, fiscal_period,
               'gl_account ' || gl_account || ' is unmapped'
        FROM stg_gl WHERE {scope_filter} AND gl_account IN ({unmapped_list})
    """).fetchall()
    counts["unmapped_account"] = _log(con, "unmapped_account", False, unmapped_rows)

    # --- non-blocking: catch_all_account (line grain) -----------------------
    catch_all_accounts = con.execute("""
        SELECT source_account FROM map_account WHERE status = 'catch_all'
    """).fetchall()
    catch_all_list = ",".join(str(a[0]) for a in catch_all_accounts) if catch_all_accounts else "NULL"
    catch_all_rows = con.execute(f"""
        SELECT company_code, document_id, line_number, fiscal_year, fiscal_period,
               'gl_account ' || gl_account || ' is catch_all (ADR-0005)'
        FROM stg_gl WHERE {scope_filter} AND gl_account IN ({catch_all_list})
    """).fetchall()
    counts["catch_all_account"] = _log(con, "catch_all_account", False, catch_all_rows)

    return counts


def main() -> int:
    con = duckdb.connect(str(WAREHOUSE_DB))
    from load_fact import PERIOD_FILTER  # local import, avoids a cycle at module load
    counts = run_gate(con, PERIOD_FILTER)
    con.close()
    for name in CHECK_NAMES:
        print(f"{name:<24} {counts.get(name, 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
