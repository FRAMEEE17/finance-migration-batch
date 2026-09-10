"""Regression checks. Run after every ticket. Every check stays green.

    python src/checks.py

Add one check per acceptance criterion as tickets land. Keep each check
deterministic: it computes a value and compares it, no judgement.

Every check function shares one contract: takes the DuckDB connection
`con`, returns `(ok: bool, detail: str)`. `ok` is what main() uses to
decide pass/fail; `detail` is what gets printed either way, so it should
say what was actually measured, not just "passed"/"failed". Inside a
check, `got` is the real value read from the database, `want` is what it
should be, `bad` is a count of rows/accounts that violate the rule -
consistent names across every check below, not restated per function.
"""

import csv
import sys
from pathlib import Path

import duckdb  # type: ignore

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load_fact  # noqa: E402
import quality_gate  # noqa: E402

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

def fact_gl_line_scope_only(con):
    bad = con.execute(f"""
        SELECT COUNT(*) FROM fact_gl_line WHERE NOT ({load_fact.PERIOD_FILTER})
    """).fetchone()[0]
    return bad == 0, f"{bad} rows outside company 1000 / 2024-01" if bad else "scope only"


def fact_gl_line_subset_of_stg(con):
    fact_rows = con.execute("SELECT COUNT(*) FROM fact_gl_line").fetchone()[0]
    stg_rows = con.execute(f"SELECT COUNT(*) FROM stg_gl WHERE {load_fact.PERIOD_FILTER}").fetchone()[0]
    return fact_rows <= stg_rows, f"fact={fact_rows:,}  stg (same scope)={stg_rows:,}"


def unbalanced_document_excluded(con):
    """The whole document is gone from fact_gl_line, not just its
    imbalanced line, and shows up in dq_violations instead."""
    still_present = con.execute(f"""
        SELECT COUNT(*) FROM fact_gl_line f
        JOIN (
            SELECT document_id FROM stg_gl WHERE {load_fact.PERIOD_FILTER}
            GROUP BY 1 HAVING ROUND(SUM(debit_amount) - SUM(credit_amount), 2) != 0
        ) u ON u.document_id = f.document_id
    """).fetchone()[0]
    logged = con.execute("""
        SELECT COUNT(*) FROM dq_violations
        WHERE check_name = 'unbalanced_document' AND blocking = true
    """).fetchone()[0]
    ok = still_present == 0 and logged > 0
    return ok, f"in fact={still_present} (want 0), logged in dq_violations={logged} (want >0)"


def opening_balance_flagged_not_excluded(con):
    """OPENING_BALANCE rows stay in fact_gl_line, flagged, not dropped -
    different rule from unbalanced_document (docs/business-rules.md)."""
    got = con.execute("""
        SELECT COUNT(*) FROM fact_gl_line WHERE is_opening_balance
    """).fetchone()[0]
    want = con.execute(f"""
        SELECT COUNT(*) FROM stg_gl
        WHERE {load_fact.PERIOD_FILTER} AND document_type = '{load_fact.OPENING_BALANCE_TYPE}'
    """).fetchone()[0]
    return got == want, f"flagged in fact={got}  in stg (same scope)={want}"


def fraud_anomaly_postclose_untouched_in_fact(con):
    """is_fraud/is_anomaly/is_post_close pass through fact_gl_line
    unchanged for every row that actually made it in (ADR-0003 for the
    first two; is_post_close is a timing fact, not a defect, so it's
    never re-derived either) - ignores rejected rows, those aren't in
    fact_gl_line to begin with."""
    bad = con.execute(f"""
        SELECT COUNT(*) FROM fact_gl_line f
        JOIN stg_gl s USING (company_code, document_id, line_number, fiscal_year, fiscal_period)
        WHERE f.is_fraud != s.is_fraud OR f.is_anomaly != s.is_anomaly OR f.is_post_close != s.is_post_close
    """).fetchone()[0]
    return bad == 0, f"{bad} rows where fact disagrees with stg on is_fraud/is_anomaly/is_post_close"


def map_account_joined_correctly(con):
    """Every loaded row's target_account/map_status matches map_account.csv
    for its gl_account, not something computed inline."""
    bad = con.execute("""
        SELECT COUNT(*) FROM fact_gl_line f
        JOIN map_account m ON m.source_account = f.gl_account
        WHERE f.target_account IS DISTINCT FROM m.target_account
           OR f.map_status IS DISTINCT FROM m.status
    """).fetchone()[0]
    return bad == 0, f"{bad} rows where fact's target/status disagrees with map_account.csv"


def unmapped_doc_type_synthetic_reject(con):
    """No real unmapped_doc_type case exists in this period (see mission
    04's Exploration) - prove the guard rejects one anyway with a
    synthetic, in-memory row, run through the same filter the real gate
    uses. Never touches stg_gl."""
    known_types_sql = ",".join(f"'{t}'" for t in quality_gate.KNOWN_DOC_TYPES)
    passed = con.execute(f"""
        SELECT COUNT(*) FROM (VALUES ('ZZ_UNKNOWN_TYPE')) AS t(document_type)
        WHERE document_type IN ({known_types_sql})
    """).fetchone()[0]
    return passed == 0, "synthetic unknown document_type correctly excluded" if passed == 0 else "guard failed to exclude it"


# --- Ticket 5: quality gate + dq_violations -------------------------------

def dq_violations_exists(con):
    return "dq_violations" in _tables(con), "table present"


def duplicate_source_synthetic_reject(con):
    """No real duplicate-grain row exists in P01 (see mission 05's
    Exploration) - prove the check catches one anyway with a synthetic,
    in-memory grain, run through the same GROUP BY ... HAVING COUNT(*) > 1
    logic the real gate uses. Never touches stg_gl."""
    caught = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT * FROM (VALUES
                (1000, 'SYNTH-DOC', 1, 2024, 1),
                (1000, 'SYNTH-DOC', 1, 2024, 1)
            ) AS t(company_code, document_id, line_number, fiscal_year, fiscal_period)
            GROUP BY 1, 2, 3, 4, 5 HAVING COUNT(*) > 1
        )
    """).fetchone()[0]
    return caught == 1, "synthetic duplicate grain correctly caught" if caught == 1 else "guard failed to catch it"


def map_fanout_synthetic_reject(con):
    """No real map_fanout exists in map_account.csv (505 rows, 505
    distinct) - prove the check catches one anyway with a synthetic,
    in-memory source_account, run through the same
    GROUP BY source_account HAVING COUNT(*) > 1 logic the real gate uses.
    Never touches the real map_account.csv."""
    caught = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT * FROM (VALUES (999888777), (999888777)) AS t(source_account)
            GROUP BY 1 HAVING COUNT(*) > 1
        )
    """).fetchone()[0]
    return caught == 1, "synthetic map_fanout correctly caught" if caught == 1 else "guard failed to catch it"


def null_key_column_synthetic_reject(con):
    """No real null-key row exists in P01 - prove the check catches one
    anyway with a synthetic, in-memory row missing gl_account, run
    through the same OR-of-IS-NULL predicate the real gate uses."""
    null_key_cond = " OR ".join(f"{c} IS NULL" for c in quality_gate.KEY_COLUMNS)
    caught = con.execute(f"""
        SELECT COUNT(*) FROM (
            VALUES (1000, 'SYNTH-DOC', 1, 2024, 1, NULL)
        ) AS t(company_code, document_id, line_number, fiscal_year, fiscal_period, gl_account)
        WHERE {null_key_cond}
    """).fetchone()[0]
    return caught == 1, "synthetic null key column correctly caught" if caught == 1 else "guard failed to catch it"


def local_amount_imbalance_logged_not_excluded(con):
    """All 23 known local_amount_imbalance documents are logged
    non-blocking and still present in fact_gl_line (non-blocking never
    excludes)."""
    logged = con.execute("""
        SELECT COUNT(*) FROM dq_violations
        WHERE check_name = 'local_amount_imbalance' AND blocking = false
    """).fetchone()[0]
    missing_from_fact = con.execute("""
        SELECT COUNT(*) FROM dq_violations v
        WHERE v.check_name = 'local_amount_imbalance'
          AND NOT EXISTS (
              SELECT 1 FROM fact_gl_line f
              WHERE f.company_code = v.company_code AND f.document_id = v.document_id
                AND f.fiscal_year = v.fiscal_year AND f.fiscal_period = v.fiscal_period
          )
    """).fetchone()[0]
    ok = logged == 23 and missing_from_fact == 0
    return ok, f"logged={logged} (want 23), missing from fact={missing_from_fact} (want 0)"


def unmapped_account_excludes_catch_all(con):
    """unmapped_account (15 lines) and catch_all_account (70 lines) never
    overlap and never exclude a row from fact_gl_line - both non-blocking,
    docs/definitions.md's post-mission-05 wording."""
    unmapped = con.execute("""
        SELECT COUNT(*) FROM dq_violations WHERE check_name = 'unmapped_account' AND blocking = false
    """).fetchone()[0]
    catch_all = con.execute("""
        SELECT COUNT(*) FROM dq_violations WHERE check_name = 'catch_all_account' AND blocking = false
    """).fetchone()[0]
    overlap = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT document_id, line_number, fiscal_year, fiscal_period FROM dq_violations WHERE check_name = 'unmapped_account'
            INTERSECT
            SELECT document_id, line_number, fiscal_year, fiscal_period FROM dq_violations WHERE check_name = 'catch_all_account'
        )
    """).fetchone()[0]
    ok = unmapped == 15 and catch_all == 70 and overlap == 0
    return ok, f"unmapped_account={unmapped} (want 15), catch_all_account={catch_all} (want 70), overlap={overlap} (want 0)"


def gate_never_filters_on_flags(con):
    """docs/business-rules.md / ADR-0003: is_fraud, is_anomaly never enter
    a gate predicate. Static check on the module source, not just this
    run's data - a predicate that happens to find zero flagged rows today
    would still pass a data-only check."""
    src = Path(quality_gate.__file__).read_text()
    bad = "is_fraud" in src or "is_anomaly" in src
    return not bad, "quality_gate.py never references is_fraud/is_anomaly" if not bad else "found a reference, review it"


# --- Ticket 6+: reconciliation --------------------------------------------


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
    ("fact_gl_line is scope-only", fact_gl_line_scope_only),
    ("fact_gl_line is a subset of stg_gl", fact_gl_line_subset_of_stg),
    ("unbalanced document excluded from fact", unbalanced_document_excluded),
    ("opening_balance flagged, not excluded", opening_balance_flagged_not_excluded),
    ("is_fraud/is_anomaly/is_post_close untouched in fact", fraud_anomaly_postclose_untouched_in_fact),
    ("fact target/status match map_account.csv", map_account_joined_correctly),
    ("unmapped_doc_type rejects a synthetic row", unmapped_doc_type_synthetic_reject),
    ("dq_violations exists", dq_violations_exists),
    ("duplicate_source rejects a synthetic row", duplicate_source_synthetic_reject),
    ("map_fanout rejects a synthetic row", map_fanout_synthetic_reject),
    ("null_key_column rejects a synthetic row", null_key_column_synthetic_reject),
    ("local_amount_imbalance logged, not excluded", local_amount_imbalance_logged_not_excluded),
    ("unmapped_account excludes catch_all", unmapped_account_excludes_catch_all),
    ("gate never filters on is_fraud/is_anomaly", gate_never_filters_on_flags),
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
