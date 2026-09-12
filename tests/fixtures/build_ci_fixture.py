"""Builds journal_entries_ci.parquet: a small, hand-built fixture with
the real source's exact 49-column schema, for CI only. Ticket 18.

Not a sample of real data - every row here is invented on purpose, to
exercise one specific gate outcome. Never point src/*.py at this file
outside CI (see tests/ci_checks.py's own docstring for why).

Built with an explicit DuckDB schema, not pandas type inference: an
all-None VARCHAR column (several here are, on purpose - most rows don't
need a reference or header_text) gets inferred as INTEGER by
pandas/pyarrow with nothing else in the column to hint otherwise, which
then fails to load through duckdb's own VARCHAR-typed real schema. Real
bug, caught the first time this fixture actually ran through the
pipeline - explicit types side-step the whole class of failure instead
of finding every column that happens to be all-None this time.

Scope is deliberately impossible to confuse with the real project scope:
company_code=9999, fiscal_year=2099, fiscal_period=1 - the real scope is
company_code=1000, fiscal_year=2024, periods 1-3, so nothing here can
collide with or masquerade as real data even by accident.

Six scenarios, one purpose each:
  - normal: clean, balanced, no findings - the control case
  - unbalanced: debit != credit -> blocking unbalanced_document
  - ab_broadcast: source='AB', document total repeated on every debit
    line instead of a per-line amount -> the exact mission-13 signature,
    non-blocking local_amount_imbalance
  - opening_balance: document_type=OPENING_BALANCE -> flagged in
    fact_gl_line, not excluded
  - duplicate: two rows sharing one grain -> blocking duplicate_source
  - unmapped: a gl_account absent from the real map_account.csv ->
    non-blocking unmapped_account

Run: python tests/fixtures/build_ci_fixture.py
"""

import sys
from pathlib import Path

import duckdb  # type: ignore

FIXTURE_PATH = Path(__file__).resolve().parent / "journal_entries_ci.parquet"

COMPANY = 9999
YEAR = 2099
PERIOD = 1

# Real, live, mapped accounts from map_account.csv - reused here so the
# "clean" scenarios exercise a real mapping, not an invented one.
ACCOUNT_A = 1000
ACCOUNT_B = 2170
UNMAPPED_ACCOUNT = 999888  # not in map_account.csv - deliberately absent

# Exact column order and type, copied from `DESCRIBE SELECT * FROM
# read_parquet('dataset/journal_entries.parquet')` - not retyped from
# memory a second time.
SCHEMA = """
    document_id VARCHAR, company_code BIGINT, fiscal_year BIGINT, fiscal_period BIGINT,
    posting_date VARCHAR, document_date VARCHAR, document_type VARCHAR, currency VARCHAR,
    exchange_rate DOUBLE, reference VARCHAR, header_text VARCHAR, created_by VARCHAR,
    source VARCHAR, business_process VARCHAR, ledger VARCHAR, is_fraud BOOLEAN,
    is_anomaly BOOLEAN, line_number BIGINT, gl_account BIGINT, debit_amount DOUBLE,
    credit_amount DOUBLE, local_amount DOUBLE, transaction_amount VARCHAR,
    cost_center VARCHAR, profit_center VARCHAR, business_unit VARCHAR, line_text VARCHAR,
    auxiliary_account_number VARCHAR, auxiliary_account_label VARCHAR, lettrage VARCHAR,
    lettrage_date VARCHAR, is_manual BOOLEAN, is_post_close BOOLEAN, source_system VARCHAR,
    approver VARCHAR, account_description VARCHAR, financial_statement_category VARCHAR,
    assignment VARCHAR, value_date VARCHAR, tax_code VARCHAR, transaction_id VARCHAR,
    account_class VARCHAR, account_class_name VARCHAR, account_sub_class VARCHAR,
    account_sub_class_name VARCHAR, predecessor_line_id VARCHAR, trading_partner VARCHAR,
    fraud_type VARCHAR, anomaly_type VARCHAR
"""

COLUMN_NAMES = [c.strip().split()[0] for c in SCHEMA.strip().split(",")]

COMMON = dict(
    posting_date="2099-01-15", document_date="2099-01-15", currency="USD",
    exchange_rate=1.0, reference=None, header_text=None, created_by="CI_FIXTURE",
    business_process="CI", ledger="0L", is_fraud=False, is_anomaly=False,
    transaction_amount=None, cost_center="CC-CI", profit_center="PC-CI",
    business_unit="BU-CI", line_text=None, auxiliary_account_number=None,
    auxiliary_account_label=None, lettrage=None, lettrage_date=None,
    is_manual=False, is_post_close=False, source_system=None, approver=None,
    account_description=None, financial_statement_category=None,
    assignment=None, value_date="2099-01-15", tax_code=None, transaction_id=None,
    account_class=None, account_class_name=None, account_sub_class=None,
    account_sub_class_name=None, predecessor_line_id=None, trading_partner=None,
    fraud_type=None, anomaly_type=None,
)


def _line(document_id, line_number, document_type, source, gl_account,
          debit_amount, credit_amount, local_amount):
    row = dict(COMMON)
    row.update(
        document_id=document_id, company_code=COMPANY, fiscal_year=YEAR,
        fiscal_period=PERIOD, document_type=document_type, source=source,
        line_number=line_number, gl_account=gl_account,
        debit_amount=debit_amount, credit_amount=credit_amount,
        local_amount=local_amount,
    )
    return tuple(row[c] for c in COLUMN_NAMES)


def build_rows():
    rows = []

    # normal: balanced on debit/credit AND local_amount, real mapped accounts
    rows += [
        _line("CI-DOC-NORMAL-001", 1, "SA", "manual", ACCOUNT_A, 1000.0, 0.0, 1000.0),
        _line("CI-DOC-NORMAL-001", 2, "SA", "manual", ACCOUNT_B, 0.0, 1000.0, -1000.0),
    ]

    # unbalanced: 500 debit vs 400 credit - never reaches fact_gl_line
    rows += [
        _line("CI-DOC-UNBALANCED-001", 1, "SA", "manual", ACCOUNT_A, 500.0, 0.0, 500.0),
        _line("CI-DOC-UNBALANCED-001", 2, "SA", "manual", ACCOUNT_B, 0.0, 400.0, -400.0),
    ]

    # ab_broadcast: debit legs balance to 1000 total, but every debit line's
    # local_amount is the document's grand total (1000.0) instead of that
    # line's own share - the exact defect mission 13 found for real.
    rows += [
        _line("CI-DOC-AB-001", 1, "KR", "AB", ACCOUNT_A, 300.0, 0.0, 1000.0),
        _line("CI-DOC-AB-001", 2, "KR", "AB", ACCOUNT_A, 400.0, 0.0, 1000.0),
        _line("CI-DOC-AB-001", 3, "KR", "AB", ACCOUNT_A, 300.0, 0.0, 1000.0),
        _line("CI-DOC-AB-001", 4, "KR", "AB", ACCOUNT_B, 0.0, 1000.0, -1000.0),
    ]

    # opening_balance: balanced, but OPENING_BALANCE doc type
    rows += [
        _line("CI-DOC-OPENBAL-001", 1, "OPENING_BALANCE", "manual", ACCOUNT_A, 5000.0, 0.0, 5000.0),
        _line("CI-DOC-OPENBAL-001", 2, "OPENING_BALANCE", "manual", ACCOUNT_B, 0.0, 5000.0, -5000.0),
    ]

    # duplicate: the exact same grain (document_id, line_number, period)
    # inserted twice - two distinct source rows, not one row read twice.
    rows += [
        _line("CI-DOC-DUP-001", 1, "SA", "manual", ACCOUNT_A, 200.0, 0.0, 200.0),
        _line("CI-DOC-DUP-001", 1, "SA", "manual", ACCOUNT_A, 200.0, 0.0, 200.0),
        _line("CI-DOC-DUP-001", 2, "SA", "manual", ACCOUNT_B, 0.0, 200.0, -200.0),
    ]

    # unmapped: balanced, but one line posts to an account absent from
    # the real map_account.csv
    rows += [
        _line("CI-DOC-UNMAPPED-001", 1, "SA", "manual", UNMAPPED_ACCOUNT, 300.0, 0.0, 300.0),
        _line("CI-DOC-UNMAPPED-001", 2, "SA", "manual", ACCOUNT_B, 0.0, 300.0, -300.0),
    ]

    return rows


def main() -> int:
    rows = build_rows()
    placeholders = ", ".join("?" for _ in COLUMN_NAMES)
    con = duckdb.connect()
    con.execute(f"CREATE TABLE fixture ({SCHEMA})")
    con.executemany(f"INSERT INTO fixture VALUES ({placeholders})", rows)
    con.execute(f"COPY fixture TO '{FIXTURE_PATH}' (FORMAT PARQUET)")
    con.close()
    print(f"wrote {FIXTURE_PATH}: {len(rows)} rows, {len(COLUMN_NAMES)} columns")
    return 0


if __name__ == "__main__":
    sys.exit(main())
