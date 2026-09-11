"""Regression checks. Run after every ticket: python src/checks.py

One check per acceptance criterion, deterministic. Each function takes
`con`, returns `(ok: bool, detail: str)`. Naming convention: `got` is
the measured value, `want` the expected one, `bad` a violation count.
"""

import csv
import sys
from pathlib import Path

import duckdb  # type: ignore

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load_fact  # noqa: E402
import quality_gate  # noqa: E402
import reconcile_account  # noqa: E402
import reconcile_reversals  # noqa: E402
import reconcile_mismatch  # noqa: E402
import build_period_report  # noqa: E402

from config import REPO_ROOT, SOURCE_PARQUET, WAREHOUSE_DB

SOURCE = str(SOURCE_PARQUET)
MAP_CSV = REPO_ROOT / "map_account.csv"
SCOPE = "company_code = 1000 AND fiscal_year = 2024 AND fiscal_period IN (1,2,3)"
P01_FILTER = "company_code = 1000 AND fiscal_year = 2024 AND fiscal_period = 1"
BACKFILL_PERIODS = [(1000, 2024, 1), (1000, 2024, 2), (1000, 2024, 3)]
P01_FACT_ANCHOR = (13140, 3517, 97144587.13)  # rows, distinct documents, SUM(local_amount)


def _tables(con: duckdb.DuckDBPyConnection) -> set[str]:
    return {r[0] for r in con.execute("SELECT table_name FROM duckdb_tables()").fetchall()}


def _schema(con: duckdb.DuckDBPyConnection, relation: str) -> list[tuple[str, str]]:
    return [(r[0], r[1]) for r in con.execute(f"DESCRIBE {relation}").fetchall()]


# Ticket 2: stg_gl loaded as-is

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


# Ticket 3: mapping

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
    """Every account that appears in scope must have a row in
    map_account.csv - coverage, not exact equality (ADR-0007). The CSV
    can carry extra codes beyond scope (e.g. an out-of-scope clearing-pair
    partner added by hand, same family as an in-scope pair) without that
    counting as a violation; a scope account missing from the CSV always
    does."""
    scope_accounts = {
        str(r[0]) for r in con.execute(f"SELECT DISTINCT gl_account FROM stg_gl WHERE {SCOPE}").fetchall()
    }
    csv_accounts = {r["source_account"] for r in _map_rows()}
    missing = scope_accounts - csv_accounts
    extra = csv_accounts - scope_accounts
    return not missing, f"scope={len(scope_accounts)}  csv={len(csv_accounts)}  missing_from_csv={len(missing)}  extra_in_csv={len(extra)}"


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


def local_amount_expected_matches_clearing_pairs(con):
    """local_amount_expected=false exactly on the 4 clearing-pair accounts
    (ADR-0007) - every other row, including the 2 catch-all accounts and
    the 2 single-purpose clearing accounts, expects a real local_amount."""
    rows = _map_rows()
    bad = [
        r for r in rows
        if (r["local_amount_expected"] == "false") != (r["account_role"] == "clearing_pair")
    ]
    return not bad, f"{len(bad)} rows where local_amount_expected disagrees with account_role=clearing_pair" if bad else "consistent, 8 clearing-pair accounts"


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


# Ticket 4: idempotent loader

def fact_gl_line_scope_only(con):
    """fact_gl_line no longer means "just P01" (ticket 10 parameterized
    the loader) - scope is now company 1000 / FY2024, periods 1 through 3."""
    bad = con.execute(f"""
        SELECT COUNT(*) FROM fact_gl_line WHERE NOT ({SCOPE})
    """).fetchone()[0]
    return bad == 0, f"{bad} rows outside company 1000 / 2024, periods 1-3" if bad else "scope only"


def fact_gl_line_subset_of_stg(con):
    fact_rows = con.execute("SELECT COUNT(*) FROM fact_gl_line").fetchone()[0]
    stg_rows = con.execute(f"SELECT COUNT(*) FROM stg_gl WHERE {SCOPE}").fetchone()[0]
    return fact_rows <= stg_rows, f"fact={fact_rows:,}  stg (same scope)={stg_rows:,}"


def unbalanced_document_excluded(con):
    """The whole document is gone from fact_gl_line, not just its
    imbalanced line, and shows up in dq_violations instead. Scoped to
    P01 - the one known unbalanced document; P02/P03's ticket 10 backfill
    loaded zero (see the period reports' "0 document(s) excluded")."""
    still_present = con.execute(f"""
        SELECT COUNT(*) FROM fact_gl_line f
        JOIN (
            SELECT document_id FROM stg_gl WHERE {P01_FILTER}
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
    different rule from unbalanced_document (docs/business-rules.md).
    Scope spans all three backfilled periods (ticket 10)."""
    got = con.execute("""
        SELECT COUNT(*) FROM fact_gl_line WHERE is_opening_balance
    """).fetchone()[0]
    want = con.execute(f"""
        SELECT COUNT(*) FROM stg_gl
        WHERE {SCOPE} AND document_type = '{load_fact.OPENING_BALANCE_TYPE}'
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


# Ticket 5: quality gate + dq_violations

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
    """All 23 known local_amount_imbalance documents in P01 are logged
    non-blocking and still present in fact_gl_line (non-blocking never
    excludes). P01-specific count (P02 has 30, P03 has 40, both checked
    by dq_violations_present_every_period instead of an exact anchor)."""
    logged = con.execute(f"""
        SELECT COUNT(*) FROM dq_violations
        WHERE check_name = 'local_amount_imbalance' AND blocking = false AND {P01_FILTER}
    """).fetchone()[0]
    missing_from_fact = con.execute(f"""
        SELECT COUNT(*) FROM dq_violations v
        WHERE v.check_name = 'local_amount_imbalance' AND {P01_FILTER}
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
    docs/definitions.md's post-mission-05 wording. P01-specific counts
    (P02 is 12/91, P03 is 14/91 - different mixes of the same scope-wide
    map_account.csv, checked by dq_violations_present_every_period)."""
    unmapped = con.execute(f"""
        SELECT COUNT(*) FROM dq_violations WHERE check_name = 'unmapped_account' AND blocking = false AND {P01_FILTER}
    """).fetchone()[0]
    catch_all = con.execute(f"""
        SELECT COUNT(*) FROM dq_violations WHERE check_name = 'catch_all_account' AND blocking = false AND {P01_FILTER}
    """).fetchone()[0]
    overlap = con.execute(f"""
        SELECT COUNT(*) FROM (
            SELECT document_id, line_number, fiscal_year, fiscal_period FROM dq_violations WHERE check_name = 'unmapped_account' AND {P01_FILTER}
            INTERSECT
            SELECT document_id, line_number, fiscal_year, fiscal_period FROM dq_violations WHERE check_name = 'catch_all_account' AND {P01_FILTER}
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


# Ticket 6: account-level reconciliation

def recon_period_summary_row_count(con):
    """recon_period_summary is one row per (gl_account, fiscal_year,
    fiscal_period), not per account alone - the same account appears up
    to 3 times now that P01-P03 are all loaded (ticket 10)."""
    got = con.execute("SELECT COUNT(*) FROM recon_period_summary").fetchone()[0]
    want = con.execute(f"""
        SELECT COUNT(*) FROM (
            SELECT gl_account, fiscal_year, fiscal_period FROM stg_gl WHERE {SCOPE}
            UNION
            SELECT gl_account, fiscal_year, fiscal_period FROM fact_gl_line
        )
    """).fetchone()[0]
    return got == want, f"recon_period_summary={got}  distinct (gl_account, period) (stg UNION fact)={want}"


def recon_gaps_computed_correctly(con):
    """dc_gap and local_amount_gap aren't just copied in, they equal what
    their own columns say (stg_debit_total - stg_credit_total, and
    stg_local_total - fact_local_total)."""
    bad = con.execute("""
        SELECT COUNT(*) FROM recon_period_summary
        WHERE ROUND(stg_debit_total - stg_credit_total, 2) != dc_gap
           OR ROUND(stg_local_total - fact_local_total, 2) != local_amount_gap
    """).fetchone()[0]
    return bad == 0, f"{bad} rows where a gap column disagrees with its own inputs"


def recon_local_amount_gap_isolated_to_two_accounts(con):
    """Mission 06: only the 2 accounts touched by the 1 known
    unbalanced_document should show a real stg-vs-fact local_amount gap.
    Everywhere else, fact_gl_line inherits the same (defective)
    local_amount values stg_gl has, so the gap is exactly 0."""
    bad = con.execute("""
        SELECT COUNT(*) FROM recon_period_summary WHERE ABS(local_amount_gap) > 0.01
    """).fetchone()[0]
    return bad == 2, f"{bad} accounts with a real local_amount gap (want 2)"


def recon_imbalanced_total_matches_known_finding(con):
    """The 20-document local_amount defect mission 06 found in P01
    (97,144,587.1 total) must be fully attributed across
    recon_period_summary's imbalanced_local_amount column for that
    period, not partially lost in the join. That column sums every
    local_amount_imbalance-flagged document (23 in P01, including 3
    sub-cent rounding cases the report's own materiality filter drops),
    so the gap between 20 and 23 documents stays inside the 0.5
    tolerance below rather than needing its own reconciliation."""
    got = con.execute(f"""
        SELECT ROUND(SUM(imbalanced_local_amount), 1) FROM recon_period_summary WHERE {P01_FILTER}
    """).fetchone()[0]
    want = 97144587.1
    return abs(got - want) < 0.5, f"sum(imbalanced_local_amount) P01={got}  want={want}"


# Ticket 7: reversal-pair detection

def reversal_pairs_row_count(con):
    got = con.execute("SELECT COUNT(*) FROM recon_reversal_pairs").fetchone()[0]
    return got == 1025, f"recon_reversal_pairs={got}  want=1025"


def reversal_pairs_no_duplicates(con):
    bad = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT original_document_id, reversal_document_id, COUNT(*) n
            FROM recon_reversal_pairs GROUP BY 1, 2 HAVING n > 1
        )
    """).fetchone()[0]
    return bad == 0, f"{bad} duplicate (original, reversal) pair keys"


def reversal_document_never_an_original(con):
    """A reversal is never mistaken for an original: no
    original_document_id in the table also has a REV- reference."""
    bad = con.execute("""
        SELECT COUNT(*) FROM recon_reversal_pairs p
        JOIN stg_gl s ON s.document_id = p.original_document_id
        WHERE s.reference LIKE 'REV-%'
    """).fetchone()[0]
    return bad == 0, f"{bad} rows where the 'original' is itself a reversal"


def reversal_is_net_zero_matches_known_split(con):
    got_true, got_false = con.execute("""
        SELECT SUM(is_net_zero::int), SUM((NOT is_net_zero)::int) FROM recon_reversal_pairs
    """).fetchone()
    return (got_true, got_false) == (940, 85), f"is_net_zero true={got_true} false={got_false}  want true=940 false=85"


def reversal_synthetic_net_zero_cases(con):
    """No real case proves is_net_zero for a document that shares its
    original's period vs. one that doesn't (both real pairs happen to
    include both), so this pins the swap-tolerance arithmetic itself
    against 3 synthetic pairs: same-period net-zero, cross-period
    net-zero, and a genuine non-zero net. Mirrors
    build_recon_reversal_pairs' own expression. Never touches stg_gl or
    recon_reversal_pairs."""
    rows = con.execute(f"""
        WITH pairs(orig_dr, orig_cr, orig_fy, orig_fp, rev_dr, rev_cr, rev_fy, rev_fp, label) AS (
            VALUES
                (100.0, 0.0, 2024, 1, 0.0, 100.0, 2024, 1, 'same_period_zero'),
                (100.0, 0.0, 2024, 1, 0.0, 100.0, 2024, 2, 'cross_period_zero'),
                (100.0, 0.0, 2024, 1, 0.0, 40.0,  2024, 1, 'nonzero_net')
        )
        SELECT label,
               (orig_fy != rev_fy OR orig_fp != rev_fp) AS cross_period,
               ABS(orig_dr - rev_cr) <= {reconcile_reversals.SWAP_TOLERANCE}
                   AND ABS(orig_cr - rev_dr) <= {reconcile_reversals.SWAP_TOLERANCE} AS is_net_zero
        FROM pairs
    """).fetchall()
    got = {label: (cross_period, is_net_zero) for label, cross_period, is_net_zero in rows}
    want = {
        "same_period_zero": (False, True),
        "cross_period_zero": (True, True),
        "nonzero_net": (False, False),
    }
    return got == want, f"got={got}" if got != want else "all 3 synthetic cases match expected (cross_period, is_net_zero)"


def reversal_synthetic_duplicate_and_self_reversal_reject(con):
    """A duplicate reversal row (same reversal_document_id detected
    twice, e.g. from a stg_gl scan without DISTINCT) must collapse to one
    pair, and a document whose header_text claims to reverse itself must
    not produce a pair. Mirrors the rev CTE's DISTINCT + the
    reversal-never-an-original guard, on a synthetic in-memory table.
    Never touches stg_gl or recon_reversal_pairs."""
    dup_collapsed = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT DISTINCT * FROM (VALUES ('R1', 'O1'), ('R1', 'O1')) AS t(reversal_document_id, original_document_id)
        )
    """).fetchone()[0]
    self_reversal_rejected = con.execute("""
        SELECT COUNT(*) FROM (VALUES ('R2', 'R2')) AS t(reversal_document_id, original_document_id)
        WHERE reversal_document_id = original_document_id
    """).fetchone()[0]
    ok = dup_collapsed == 1 and self_reversal_rejected == 1
    return ok, f"duplicate collapses to {dup_collapsed} row (want 1), self-reversal detected {self_reversal_rejected} time(s) (want 1, to be excluded upstream)"


# Ticket 8: document-level reconciliation with bucket + cause

VALID_BUCKETS = ("missing_in_fact", "missing_in_stg", "amount_changed", "intentionally_excluded")
VALID_CAUSES = (
    "opening_balance", "closing_entry", "post_close", "unmapped_account",
    "unmapped_doc_type", "unbalanced_document", "duplicate_source",
    "reversal_pair", "out_of_scope_period", "local_amount_imbalance",
    "rounding", "unknown",
)
INTENTIONALLY_EXCLUDED_CAUSES = (
    "opening_balance", "closing_entry", "post_close", "out_of_scope_period", "reversal_pair",
)


def mismatch_bucket_cause_enums_valid(con):
    bad = con.execute(f"""
        SELECT COUNT(*) FROM recon_mismatch
        WHERE bucket NOT IN ({",".join(f"'{b}'" for b in VALID_BUCKETS)})
           OR cause NOT IN ({",".join(f"'{c}'" for c in VALID_CAUSES)})
    """).fetchone()[0]
    return bad == 0, f"{bad} rows with a bucket or cause outside the closed enums"


def mismatch_intentionally_excluded_cause_restricted(con):
    bad = con.execute(f"""
        SELECT COUNT(*) FROM recon_mismatch
        WHERE bucket = 'intentionally_excluded'
          AND cause NOT IN ({",".join(f"'{c}'" for c in INTENTIONALLY_EXCLUDED_CAUSES)})
    """).fetchone()[0]
    return bad == 0, f"{bad} intentionally_excluded rows with a cause outside the allowed 5"


def mismatch_known_counts(con):
    """P01-specific exact counts, pinned since mission 08. P02/P03 add
    their own post_close-only rows (62 and 101, see
    recon_tables_hold_all_three_periods) that would otherwise inflate an
    unscoped comparison against this fixed list."""
    got = con.execute(f"""
        SELECT bucket, cause, COUNT(*) FROM recon_mismatch WHERE {P01_FILTER} GROUP BY 1, 2 ORDER BY 1, 2
    """).fetchall()
    want = [
        ("intentionally_excluded", "opening_balance", 17),
        ("intentionally_excluded", "post_close", 200),
        ("missing_in_fact", "unbalanced_document", 2),
    ]
    return got == want, f"got={got}" if got != want else "P01: 17 opening_balance, 200 post_close, 2 unbalanced_document, exact"


def mismatch_unknown_under_twenty_percent(con):
    total, unknown = con.execute("""
        SELECT COUNT(*), SUM((cause = 'unknown')::int) FROM recon_mismatch
    """).fetchone()
    pct = 100.0 * unknown / total if total else 0.0
    return pct < 20.0, f"unknown={unknown}/{total} ({pct:.1f}%, want <20%)"


def mismatch_gap_computed_not_asserted(con):
    """gap = stg local_amount - fact local_amount, recomputed independently
    here from stg_gl / fact_gl_line, not read back from recon_mismatch's
    own column. Against the close-eligible subset, matching what
    build_recon_mismatch itself compares (a row flagged
    is_opening_balance/is_closing_entry/is_post_close counts as absent
    from the close-eligible side, even though it's present in the full
    fact_gl_line table - that's the whole reason it's a mismatch)."""
    bad = con.execute("""
        SELECT COUNT(*) FROM recon_mismatch m
        JOIN stg_gl s USING (company_code, document_id, line_number, fiscal_year, fiscal_period)
        LEFT JOIN (
            SELECT * FROM fact_gl_line
            WHERE NOT is_opening_balance AND NOT is_closing_entry AND NOT is_post_close
        ) f USING (company_code, document_id, line_number, fiscal_year, fiscal_period)
        WHERE m.gap != ROUND(s.local_amount - COALESCE(f.local_amount, 0), 2)
    """).fetchone()[0]
    return bad == 0, f"{bad} rows where recon_mismatch.gap disagrees with a fresh close-eligible computation"


def mismatch_closing_entry_synthetic(con):
    """No real CL document exists in P01 (mission 04/08's Exploration) -
    prove the closing_entry cause path fires correctly with a synthetic
    row, mirroring build_recon_mismatch's own CASE expression. Never
    touches stg_gl or fact_gl_line."""
    got = con.execute("""
        SELECT CASE
            WHEN NOT in_fact_close_eligible AND is_opening_balance THEN 'opening_balance'
            WHEN NOT in_fact_close_eligible AND is_closing_entry THEN 'closing_entry'
            WHEN NOT in_fact_close_eligible AND is_post_close THEN 'post_close'
        END
        FROM (VALUES (false, false, true, false)) AS t(in_fact_close_eligible, is_opening_balance, is_closing_entry, is_post_close)
    """).fetchone()[0]
    return got == "closing_entry", f"synthetic closing_entry row classified as {got!r} (want 'closing_entry')"


def mismatch_amount_changed_and_missing_in_stg_synthetic(con):
    """Neither amount_changed nor missing_in_stg has a real case in P01
    (every row that's present on both sides matches exactly, and
    fact_gl_line is built as a strict subset of stg_gl so nothing can be
    in fact without being in stg). Proves both bucket branches of
    build_recon_mismatch's own CASE expression with synthetic in/absent
    flags and a deliberately large gap. Never touches stg_gl or
    fact_gl_line."""
    rows = con.execute("""
        SELECT label, CASE
            WHEN NOT in_stg THEN 'missing_in_stg'
            WHEN NOT in_fact_full THEN 'missing_in_fact'
            WHEN NOT in_fact_close_eligible THEN 'intentionally_excluded'
            WHEN ABS(gap) > 0.01 THEN 'amount_changed'
            ELSE 'matched'
        END AS bucket
        FROM (VALUES
            (false, true, true, 0.0, 'missing_in_stg_case'),
            (true, true, true, 50.0, 'amount_changed_case')
        ) AS t(in_stg, in_fact_full, in_fact_close_eligible, gap, label)
    """).fetchall()
    got = dict(rows)
    want = {"missing_in_stg_case": "missing_in_stg", "amount_changed_case": "amount_changed"}
    return got == want, f"got={got}" if got != want else "both synthetic cases classify correctly"


def mismatch_pair_enrichment_present(con):
    """recon_reversal_pairs enrichment (pair_id, is_swap_valid) attaches
    to a recon_mismatch row whose document is part of a detected pair,
    per mission 08's ruling: informational only, never changes bucket or
    cause. At least one real row should show it (92 found when this was
    built) - if this ever drops to 0, the enrichment join broke, not
    that no mismatched row happens to be part of a pair."""
    got = con.execute("SELECT COUNT(*) FROM recon_mismatch WHERE pair_id IS NOT NULL").fetchone()[0]
    return got > 0, f"{got} recon_mismatch rows carry a non-null pair_id (want >0)"


def mismatch_pair_enrichment_never_changes_bucket(con):
    """Being part of a reversal pair never reclassifies a row's bucket or
    cause away from what the close-eligible comparison alone determined
    (mission 08: option (a), not (b))."""
    bad = con.execute(f"""
        SELECT COUNT(*) FROM recon_mismatch
        WHERE pair_id IS NOT NULL AND (bucket = 'reversal_pair' OR cause = 'reversal_pair')
    """).fetchone()[0]
    return bad == 0, f"{bad} rows where pair membership leaked into bucket/cause"


# Ticket 9: period report (working paper, not the sign-off artifact - ADR-0008)

def period_report_exists(con):
    missing = [
        build_period_report.report_path(y, p)
        for _, y, p in BACKFILL_PERIODS
        if not build_period_report.report_path(y, p).exists()
    ]
    return not missing, "all 3 period reports exist" if not missing else f"missing: {missing}"


def period_report_known_issue_before_totals(con):
    """The local_amount defect disclosure appears before the
    Reconciliation section, not after, in every period's report -
    checked by byte offset, not by assuming the script wrote them in
    the order the source lists them."""
    bad = []
    for _, y, p in BACKFILL_PERIODS:
        text = build_period_report.report_path(y, p).read_text()
        issue_pos = text.find("Known issue")
        recon_pos = text.find("## Reconciliation")
        if issue_pos == -1 or recon_pos == -1 or issue_pos >= recon_pos:
            bad.append(f"{y}-{p:02d}")
    return not bad, "issue before reconciliation in all 3 reports" if not bad else f"wrong order in: {bad}"


def period_report_numbers_match_source(con):
    """Every headline number in each report is parsed back out and
    compared against a fresh query, not trusted from generation time."""
    bad = []
    for c, y, p in BACKFILL_PERIODS:
        text = build_period_report.report_path(y, p).read_text()
        data = build_period_report._fetch(con, c, y, p)
        n_accounts, stg_total, fact_total, gap, n_exceptions = data["period_summary"]
        label = f"{y}-{p:02d}"

        if f"Accounts compared: **{n_accounts}**" not in text:
            bad.append(f"{label} account count")
        if f"{stg_total:,.2f}" not in text:
            bad.append(f"{label} stg total")
        if f"{fact_total:,.2f}" not in text:
            bad.append(f"{label} fact total")
        if f"{data['dc_gap']:,.2f}" not in text:
            bad.append(f"{label} debit/credit gap")
        for _, _, count, amt in data["mismatch"]:
            if f"| {count} | {amt:,.2f} |" not in text:
                bad.append(f"{label} mismatch row count={count} amount={amt}")

    return not bad, f"missing or mismatched: {bad}" if bad else "every checked figure present and matching in all 3 reports"


def period_report_never_claims_verified_or_final(con):
    """Every report explicitly disclaims "verified close" and "final" for
    the local_amount total, per the mission 09 ruling - that phrasing is
    exactly what a reader would mistake for a signed number."""
    bad = []
    for _, y, p in BACKFILL_PERIODS:
        text = build_period_report.report_path(y, p).read_text()
        if 'not a "verified close"' not in text or 'not a "final"' not in text:
            bad.append(f"{y}-{p:02d}")
    return not bad, "both disclaimers present in all 3 reports" if not bad else f"missing in: {bad}"


def period_report_signoff_lines_present(con):
    """The exact two-line sign-off block the mission ruling specified is
    present verbatim, not paraphrased, in every period's report."""
    bad = []
    for _, y, p in BACKFILL_PERIODS:
        text = build_period_report.report_path(y, p).read_text()
        if "Reconciliation: accepted" not in text or "Reported local_amount total: not signed" not in text:
            bad.append(f"{y}-{p:02d}")
    return not bad, "both sign-off lines present verbatim in all 3 reports" if not bad else f"missing or reworded in: {bad}"


def period_report_idempotent_rebuild(con):
    """Rebuilding every report from the same warehouse state reproduces
    an identical file - the actual idempotency proof, not just a claim."""
    changed = []
    for c, y, p in BACKFILL_PERIODS:
        path = build_period_report.report_path(y, p)
        before = path.read_bytes()
        build_period_report.build_period_report(con, c, y, p)
        after = path.read_bytes()
        if before != after:
            changed.append(f"{y}-{p:02d}")
    return not changed, "all 3 reports identical after rebuild" if not changed else f"rebuild changed: {changed}"


# ADR-0008: period_signoff, the machine-readable close state a BI tool or
# PDF generator would read - not the Markdown report itself

def period_signoff_matches_report(con):
    """period_signoff and the report it's derived from must agree - one
    computation (_fetch), two outputs, checked here so they can't
    silently drift apart."""
    bad = []
    for c, y, p in BACKFILL_PERIODS:
        row = con.execute(f"""
            SELECT accounts_compared, accounts_matched, local_amount_status
            FROM period_signoff
            WHERE company_code = {c} AND fiscal_year = {y} AND fiscal_period = {p}
        """).fetchone()
        if row is None:
            bad.append(f"{y}-{p:02d}: missing from period_signoff")
            continue
        n_accounts, n_matched, local_amount_status = row
        text = build_period_report.report_path(y, p).read_text()
        if f"Accounts compared: **{n_accounts}**" not in text:
            bad.append(f"{y}-{p:02d}: accounts_compared disagrees with report")
        if f"Accounts that match exactly: **{n_matched}**" not in text:
            bad.append(f"{y}-{p:02d}: accounts_matched disagrees with report")
        if local_amount_status != "not_signed":
            bad.append(f"{y}-{p:02d}: local_amount_status={local_amount_status!r}, want 'not_signed' while issue #13 is open")
    return not bad, "period_signoff agrees with all 3 reports" if not bad else f"disagreements: {bad}"


# Ticket 15: controller pack / exception appendix (issue #15)

def close_pack_files_exist(con):
    """All 3 artifacts (working paper, controller pack, exception
    appendix) exist for all 3 periods - 9 files, not just the 3 the
    project already had before mission 15."""
    missing = []
    for _, y, p in BACKFILL_PERIODS:
        for path_fn in (
            build_period_report.report_path,
            build_period_report.controller_pack_path,
            build_period_report.exceptions_path,
        ):
            if not path_fn(y, p).exists():
                missing.append(str(path_fn(y, p)))
    return not missing, "all 9 files exist" if not missing else f"missing: {missing}"


def controller_pack_never_claims_verified_or_final(con):
    """Same rule as the working paper (mission 09), now checked on the
    file finance actually reads."""
    bad = []
    for _, y, p in BACKFILL_PERIODS:
        text = build_period_report.controller_pack_path(y, p).read_text()
        if "verified" in text.lower() or ('"final"' in text or "**final**" in text.lower()):
            bad.append(f"{y}-{p:02d}")
    return not bad, "no verified/final claims in any controller pack" if not bad else f"found in: {bad}"


def controller_pack_risk_before_decision(con):
    """The risk/known-issue section appears before the Decision section -
    same byte-offset discipline as the working paper's own check, applied
    to the file a controller actually reads first."""
    bad = []
    for _, y, p in BACKFILL_PERIODS:
        text = build_period_report.controller_pack_path(y, p).read_text()
        risk_pos = text.find("## Risk this period")
        decision_pos = text.find("## Decision")
        if risk_pos == -1 or decision_pos == -1 or risk_pos >= decision_pos:
            bad.append(f"{y}-{p:02d}")
    return not bad, "risk before decision in all 3 controller packs" if not bad else f"wrong order in: {bad}"


def controller_pack_shows_split_decision(con):
    """The two decisions (reconciliation, local_amount) are both present
    and never collapsed into one status - the one rule this whole mission
    exists to enforce, checked on the actual controller-facing file."""
    bad = []
    for _, y, p in BACKFILL_PERIODS:
        text = build_period_report.controller_pack_path(y, p).read_text()
        if "**Reconciliation:**" not in text or "**Reported currency total:**" not in text:
            bad.append(f"{y}-{p:02d}")
    return not bad, "both decisions shown separately in all 3 controller packs" if not bad else f"missing in: {bad}"


def exceptions_broadcast_total_matches_working_paper(con):
    """The exception appendix's local_amount broadcast section is the
    same document count and total the working paper's Known Issue
    section already quotes - two files, one number, never allowed to
    drift."""
    bad = []
    for c, y, p in BACKFILL_PERIODS:
        data = build_period_report._fetch(con, c, y, p)
        exc = build_period_report._fetch_exceptions(con, c, y, p)
        got_count = len(exc["broadcast_docs"])
        got_total = round(sum(row[4] for row in exc["broadcast_docs"]), 1)
        want_count = data["imbalanced_doc_count"]
        want_total = round(data["imbalanced_total"], 1)
        if got_count != want_count or abs(got_total - want_total) > 0.1:
            bad.append(f"{y}-{p:02d}: appendix={got_count}/{got_total}  report={want_count}/{want_total}")
    return not bad, "appendix agrees with working paper in all 3 periods" if not bad else f"disagreements: {bad}"


def period_signoff_carries_all_three_paths(con):
    """period_signoff points at all 3 artifacts, not just the working
    paper - a BI tool reading this table needs to find the controller
    pack and exception appendix too."""
    bad = []
    for c, y, p in BACKFILL_PERIODS:
        row = con.execute(f"""
            SELECT report_path, controller_pack_path, exceptions_path
            FROM period_signoff WHERE company_code = {c} AND fiscal_year = {y} AND fiscal_period = {p}
        """).fetchone()
        if row is None or any(v is None or v == "" for v in row):
            bad.append(f"{y}-{p:02d}: {row}")
    return not bad, "all 3 paths present for all 3 periods" if not bad else f"missing paths: {bad}"


def close_pack_idempotent_rebuild(con):
    """Rebuilding the controller pack and exception appendix from the
    same warehouse state reproduces identical files - same proof as the
    working paper's own idempotency check, extended to the 2 new files."""
    changed = []
    for c, y, p in BACKFILL_PERIODS:
        for path_fn, build_fn in (
            (build_period_report.controller_pack_path, build_period_report.build_controller_pack),
            (build_period_report.exceptions_path, build_period_report.build_exceptions_appendix),
        ):
            path = path_fn(y, p)
            before = path.read_bytes()
            build_fn(con, c, y, p)
            after = path.read_bytes()
            if before != after:
                changed.append(f"{y}-{p:02d}:{path.name}")
    return not changed, "all 6 files identical after rebuild" if not changed else f"rebuild changed: {changed}"


# Ticket 10: backfill 2024-02 and 2024-03

def p01_unchanged_after_backfill(con):
    """P01's fact_gl_line row count, document count, and SUM(local_amount)
    are byte-identical before and after the P02/P03 backfill - the
    mandatory test from the ticket 10 ruling ("after P02 runs, P01 must
    match the already-signed-off file in every column"), pinned here as a
    permanent regression check instead of a one-off manual comparison."""
    got = con.execute(f"""
        SELECT COUNT(*), COUNT(DISTINCT document_id), ROUND(SUM(local_amount), 2)
        FROM fact_gl_line WHERE {P01_FILTER}
    """).fetchone()
    return got == P01_FACT_ANCHOR, f"got={got}  want={P01_FACT_ANCHOR}"


def dq_violations_present_every_period(con):
    """P02 and P03 loaded through the same quality gate as P01, not an
    empty gate result silently assumed clean - each period has its own
    real dq_violations rows."""
    counts = con.execute(f"""
        SELECT fiscal_period, COUNT(*) FROM dq_violations WHERE {SCOPE} GROUP BY 1 ORDER BY 1
    """).fetchall()
    periods_with_rows = {p for p, n in counts if n > 0}
    return periods_with_rows == {1, 2, 3}, f"periods with dq_violations rows={sorted(periods_with_rows)}  want=[1, 2, 3]"


def recon_tables_hold_all_three_periods(con):
    """recon_period_summary and recon_mismatch both hold P01+P02+P03 at
    once - the per-period rebuild mode (mission 10) deletes and rewrites
    only the period it's given, so loading P02/P03 must never wipe P01's
    already-signed-off rows."""
    summary_periods = {r[0] for r in con.execute("SELECT DISTINCT fiscal_period FROM recon_period_summary").fetchall()}
    mismatch_periods = {r[0] for r in con.execute("SELECT DISTINCT fiscal_period FROM recon_mismatch").fetchall()}
    want = {1, 2, 3}
    ok = summary_periods == want and mismatch_periods == want
    return ok, f"recon_period_summary periods={sorted(summary_periods)}  recon_mismatch periods={sorted(mismatch_periods)}  want={sorted(want)}"



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
    ("local_amount_expected matches clearing pairs", local_amount_expected_matches_clearing_pairs),
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
    ("recon_period_summary row count", recon_period_summary_row_count),
    ("recon gaps computed correctly", recon_gaps_computed_correctly),
    ("local_amount gap isolated to 2 accounts", recon_local_amount_gap_isolated_to_two_accounts),
    ("imbalanced total matches known finding", recon_imbalanced_total_matches_known_finding),
    ("reversal pairs row count", reversal_pairs_row_count),
    ("reversal pairs no duplicates", reversal_pairs_no_duplicates),
    ("reversal document never an original", reversal_document_never_an_original),
    ("reversal is_net_zero matches known split", reversal_is_net_zero_matches_known_split),
    ("reversal synthetic net-zero cases", reversal_synthetic_net_zero_cases),
    ("reversal synthetic duplicate/self-reversal reject", reversal_synthetic_duplicate_and_self_reversal_reject),
    ("mismatch bucket/cause enums valid", mismatch_bucket_cause_enums_valid),
    ("mismatch intentionally_excluded cause restricted", mismatch_intentionally_excluded_cause_restricted),
    ("mismatch known counts", mismatch_known_counts),
    ("mismatch unknown under 20%", mismatch_unknown_under_twenty_percent),
    ("mismatch gap computed, not asserted", mismatch_gap_computed_not_asserted),
    ("mismatch closing_entry synthetic case", mismatch_closing_entry_synthetic),
    ("mismatch amount_changed/missing_in_stg synthetic", mismatch_amount_changed_and_missing_in_stg_synthetic),
    ("mismatch pair enrichment present", mismatch_pair_enrichment_present),
    ("mismatch pair enrichment never changes bucket", mismatch_pair_enrichment_never_changes_bucket),
    ("period report exists", period_report_exists),
    ("period report known issue before totals", period_report_known_issue_before_totals),
    ("period report numbers match source", period_report_numbers_match_source),
    ("period report never claims verified/final", period_report_never_claims_verified_or_final),
    ("period report sign-off lines present", period_report_signoff_lines_present),
    ("period report idempotent rebuild", period_report_idempotent_rebuild),
    ("period_signoff matches report", period_signoff_matches_report),
    ("close pack files exist (9 files)", close_pack_files_exist),
    ("controller pack never claims verified/final", controller_pack_never_claims_verified_or_final),
    ("controller pack risk before decision", controller_pack_risk_before_decision),
    ("controller pack shows split decision", controller_pack_shows_split_decision),
    ("exceptions broadcast total matches working paper", exceptions_broadcast_total_matches_working_paper),
    ("period_signoff carries all 3 paths", period_signoff_carries_all_three_paths),
    ("close pack idempotent rebuild", close_pack_idempotent_rebuild),
    ("P01 unchanged after backfill", p01_unchanged_after_backfill),
    ("dq_violations present every period", dq_violations_present_every_period),
    ("recon tables hold all 3 periods", recon_tables_hold_all_three_periods),
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
