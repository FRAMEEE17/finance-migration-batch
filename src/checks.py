"""Regression checks. Run after every ticket. Every check stays green.

    python src/checks.py

Add one check per acceptance criterion as tickets land. Keep each check
deterministic: it computes a value and compares it, no judgement.
"""

import csv
import sys

import duckdb  # type: ignore

from config import REPO_ROOT, SOURCE_PARQUET, WAREHOUSE_DB

SOURCE = str(SOURCE_PARQUET)
MAP_CSV = REPO_ROOT / "map_account.csv"
SCOPE = "company_code = 1000 AND fiscal_year = 2024 AND fiscal_period IN (1,2,3)"


def _tables(con: duckdb.DuckDBPyConnection) -> set[str]:
    return {r[0] for r in con.execute("SELECT table_name FROM duckdb_tables()").fetchall()}


def _schema(con: duckdb.DuckDBPyConnection, relation: str) -> list[tuple[str, str]]:
    return [(r[0], r[1]) for r in con.execute(f"DESCRIBE {relation}").fetchall()]


# --- Ticket 2: stg_gl loaded as-is ----------------------------------------

def stg_gl_exists(con):
    return "stg_gl" in _tables(con), "table present"


def stg_gl_row_count_matches_source(con):
    got = con.execute("SELECT COUNT(*) FROM stg_gl").fetchone()[0]
    want = con.execute(f"SELECT COUNT(*) FROM read_parquet('{SOURCE}')").fetchone()[0]
    return got == want, f"stg_gl={got:,}  source={want:,}"


def stg_gl_schema_matches_source(con):
    got = _schema(con, "stg_gl")
    want = _schema(con, f"SELECT * FROM read_parquet('{SOURCE}')")
    return got == want, f"{len(got)} columns, name + type identical"


def stg_gl_document_count_stable(con):
    got = con.execute("SELECT COUNT(DISTINCT document_id) FROM stg_gl").fetchone()[0]
    return got == 174_944, f"distinct document_id = {got:,} (anchor 174,944)"


# --- Ticket 3: mapping -----------------------------------------------------

def _map_rows():
    with open(MAP_CSV, newline="") as f:
        return list(csv.DictReader(f))


def map_account_exists(con):
    return MAP_CSV.exists(), f"{MAP_CSV}"


def map_account_source_unique(con):
    rows = _map_rows()
    accounts = [r["source_account"] for r in rows]
    return len(accounts) == len(set(accounts)), f"{len(rows)} rows, {len(set(accounts))} distinct"


def map_account_covers_scope(con):
    scope_accounts = {
        str(r[0]) for r in con.execute(f"SELECT DISTINCT gl_account FROM stg_gl WHERE {SCOPE}").fetchall()
    }
    csv_accounts = {r["source_account"] for r in _map_rows()}
    return scope_accounts == csv_accounts, f"scope={len(scope_accounts)}  csv={len(csv_accounts)}"


MAP_ACCOUNT_STATUSES = ("mapped", "unmapped", "deprecated", "catch_all")  # ADR-0005


def map_account_status_valid(con):
    rows = _map_rows()
    bad = [r for r in rows if r["status"] not in MAP_ACCOUNT_STATUSES]
    return not bad, f"{len(bad)} rows with an invalid status" if bad else "all valid"


def map_account_target_consistent_with_status(con):
    """unmapped rows never carry a target. mapped and catch_all rows always
    do. deprecated only needs one when source_usage=live (docs/definitions.md)."""
    rows = _map_rows()
    bad = []
    for r in rows:
        has_target = bool(r["target_account"])
        if r["status"] == "unmapped" and has_target:
            bad.append(r)
        elif r["status"] in ("mapped", "catch_all") and not has_target:
            bad.append(r)
        elif r["status"] == "deprecated" and r["source_usage"] == "live" and not has_target:
            bad.append(r)
    return not bad, f"{len(bad)} rows where target presence disagrees with status" if bad else "consistent"


def catch_all_always_flagged(con):
    """ADR-0005: catch_all accounts are always fs_category_flag=true in
    dim_account, forced regardless of what the current scope alone shows."""
    catch_all_accounts = [int(r["source_account"]) for r in _map_rows() if r["status"] == "catch_all"]
    if not catch_all_accounts:
        return True, "no catch_all rows yet"
    placeholders = ",".join(str(a) for a in catch_all_accounts)
    bad = con.execute(f"""
        SELECT COUNT(*) FROM dim_account
        WHERE gl_account IN ({placeholders}) AND fs_category_flag != true
    """).fetchone()[0]
    return bad == 0, f"{bad} of {len(catch_all_accounts)} catch_all accounts not flagged"


def clearing_pairs_complete(con):
    """Every clearing_pair row has a pair_id, a partner row with the same
    pair_id, and both sides share the same status."""
    rows = [r for r in _map_rows() if r["account_role"] == "clearing_pair"]
    if not rows:
        return True, "no clearing_pair rows yet"
    by_pair: dict[str, list] = {}
    for r in rows:
        by_pair.setdefault(r["pair_id"], []).append(r)
    bad = [
        pid for pid, members in by_pair.items()
        if len(members) != 2 or members[0]["status"] != members[1]["status"]
    ]
    return not bad, f"{len(bad)} incomplete or status-mismatched pairs" if bad else f"{len(by_pair)} pairs, all complete"


def dim_account_row_count(con):
    got = con.execute("SELECT COUNT(*) FROM dim_account").fetchone()[0]
    want = con.execute(f"SELECT COUNT(DISTINCT gl_account) FROM stg_gl WHERE {SCOPE}").fetchone()[0]
    return got == want, f"dim_account={got}  distinct gl_account={want}"


def gl_account_to_class_is_1to1(con):
    bad = con.execute(f"""
        SELECT COUNT(*) FROM (
            SELECT gl_account FROM stg_gl WHERE {SCOPE}
            GROUP BY 1 HAVING COUNT(DISTINCT COALESCE(account_class, '<null>')) > 1
        )
    """).fetchone()[0]
    return bad == 0, f"{bad} accounts map to more than one class"


def fraud_anomaly_accounts_not_excluded(con):
    """The account set backing map_account.csv must not have been filtered
    by is_fraud / is_anomaly (ADR-0003)."""
    with_flags = {
        str(r[0]) for r in con.execute(
            f"SELECT DISTINCT gl_account FROM stg_gl WHERE {SCOPE} AND (is_fraud OR is_anomaly)"
        ).fetchall()
    }
    csv_accounts = {r["source_account"] for r in _map_rows()}
    missing = with_flags - csv_accounts
    return not missing, f"{len(missing)} flagged-row accounts missing from map_account.csv" if missing else f"{len(with_flags)} flagged-row accounts present"


# --- Ticket 4: idempotent loader ----------------------------------------
# --- Ticket 5+: quality gate, reconciliation ---------------------------


CHECKS = [
    ("stg_gl exists", stg_gl_exists),
    ("stg_gl row count == source", stg_gl_row_count_matches_source),
    ("stg_gl schema == source", stg_gl_schema_matches_source),
    ("stg_gl document count stable", stg_gl_document_count_stable),
    ("map_account.csv exists", map_account_exists),
    ("map_account.csv source_account unique", map_account_source_unique),
    ("map_account.csv covers scope gl_accounts", map_account_covers_scope),
    ("map_account.csv status is valid", map_account_status_valid),
    ("map_account.csv target/status consistent", map_account_target_consistent_with_status),
    ("catch_all accounts always flagged", catch_all_always_flagged),
    ("clearing pairs complete", clearing_pairs_complete),
    ("dim_account row count == distinct gl_account", dim_account_row_count),
    ("gl_account -> account_class is 1:1", gl_account_to_class_is_1to1),
    ("fraud/anomaly accounts not excluded", fraud_anomaly_accounts_not_excluded),
]


def main() -> int:
    con = duckdb.connect(str(WAREHOUSE_DB), read_only=True)
    failed = 0
    for name, fn in CHECKS:
        try:
            ok, detail = fn(con)
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"error: {exc}"
        print(f"{'ok  ' if ok else 'FAIL'}  {name:<32} {detail}")
        failed += not ok
    con.close()
    print(f"\n{len(CHECKS) - failed}/{len(CHECKS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
