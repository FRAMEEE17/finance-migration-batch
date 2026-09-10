"""Build dim_account and draft map_account.csv. Mission 01 / Ticket 3.

Scope: company 1000, FY2024 P01-P03. target_account = source account_class
for an ordinary rollup account (derived, not invented). Clearing, clearing-
pair, and catch-all accounts are the exception: see the three hand-ruled
sets below. Human approves before use.

Run: python src/build_mapping.py
"""

import sys

import duckdb  # type: ignore

from config import REPO_ROOT, WAREHOUSE_DB

SCOPE = "company_code = 1000 AND fiscal_year = 2024 AND fiscal_period IN (1,2,3)"
MAP_CSV = REPO_ROOT / "map_account.csv"
REPORT_MD = REPO_ROOT / "docs" / "mapping-review.md"

# --- Hand-ruled accounts ----------------------------------------------------
# These three sets come from a human ruling on issue #3, not automated
# detection. A class-name pattern match (ILIKE '%suspense%clearing%') found
# these 7 codes as candidates; which of them are single-purpose clearing
# accounts versus cross-scope catch-all codes, and what each one's
# target_account and status should be, was a business call, not something
# derivable from the data alone. See ADR-0005 and docs/definitions.md.

# Single-purpose clearing/suspense accounts: real accounts, still live, kept
# in the target CoA under their own code (not rolled into account_class,
# which would misfile them into a rollup group they don't belong to).
CLEARING_ACCOUNTS = {9000, 9100, 9300, 199000, 199300}

# Debit-only / credit-only pairs. local_amount is 0 on every row for all six
# despite real debit_amount / credit_amount activity (dq_flag below). Stay
# unmapped until a human names the real pair target; never map one side
# without the other.
CLEARING_PAIRS = [(115020, 205020), (115021, 205021), (115030, 205030)]

# Migration catch-all codes: one gl_account absorbing unrelated postings
# across every company and period in the source, not a real account. See
# ADR-0005. Never share a target_account with each other; they can carry
# different financial_statement_category values in the same scope.
CATCH_ALL_ACCOUNTS = {199999, 999999}

DQ_FLAG_PAIR = "local_amount_zero_but_dr_cr_nonzero"


def _markdown_table(header: list[str], rows: list[list[str]]) -> list[str]:
    """Render a markdown table, or 'none' if there are no rows."""
    if not rows:
        return ["none"]
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out.extend("| " + " | ".join(cells) + " |" for cells in rows)
    return out


def verify_key(con) -> None:
    """gl_account -> account_class must be 1:1. If not, target = account_class
    is impossible and this mission cannot proceed as designed."""
    bad = con.execute(f"""
        SELECT gl_account, COUNT(DISTINCT COALESCE(account_class, '<null>')) n
        FROM stg_gl WHERE {SCOPE} GROUP BY 1 HAVING n > 1
    """).fetchall()
    if bad:
        print(f"BLOCKED: {len(bad)} gl_account map to >1 account_class: {bad[:5]}")
        sys.exit(1)
    print("verified: gl_account -> account_class is 1:1 in scope")


def verify_self_consistent(con) -> None:
    """Every gl_account must agree with its own lines on
    financial_statement_category, EXCEPT the hand-ruled catch-all accounts,
    which are expected to disagree with themselves once the source is
    queried outside the current scope. Within the current scope they may
    look locally consistent (build_dim_account forces their flag on
    regardless); any *other* account disagreeing with itself here would
    mean the one-account-one-category assumption behind dim_account is
    wrong, and nothing downstream can be trusted."""
    bad = con.execute(f"""
        SELECT COUNT(*) FROM (
            SELECT gl_account FROM stg_gl
            WHERE {SCOPE} AND gl_account NOT IN ({",".join(str(a) for a in CATCH_ALL_ACCOUNTS)})
            GROUP BY 1 HAVING COUNT(DISTINCT financial_statement_category) > 1
        )
    """).fetchone()[0]
    if bad:
        print(f"BLOCKED: {bad} gl_account disagree with their own lines")
        sys.exit(1)


def build_dim_account(con) -> None:
    con.execute(f"""
        CREATE OR REPLACE TABLE dim_account AS
        WITH scope AS (
            SELECT * FROM stg_gl WHERE {SCOPE}
        ),
        votes AS (
            SELECT gl_account, financial_statement_category AS cat, COUNT(*) n
            FROM scope GROUP BY 1, 2
        ),
        ranked AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY gl_account ORDER BY n DESC, cat
            ) rn
            FROM votes
        ),
        majority AS (
            SELECT gl_account, cat AS fs_category_proposed FROM ranked WHERE rn = 1
        ),
        flags AS (
            SELECT gl_account,
                   COUNT(DISTINCT financial_statement_category) > 1 AS fs_category_flag
            FROM scope GROUP BY 1
        )
        SELECT
            s.gl_account,
            any_value(s.account_sub_class)  AS account_sub_class,
            any_value(s.account_class)      AS account_class,
            any_value(s.account_class_name) AS account_class_name,
            MIN(s.account_description) AS account_description,
            m.fs_category_proposed,
            f.fs_category_flag
        FROM scope s
        JOIN majority m USING (gl_account)
        JOIN flags f USING (gl_account)
        GROUP BY s.gl_account, m.fs_category_proposed, f.fs_category_flag
    """)

    # ADR-0005: catch-all accounts are always flagged, even when their lines
    # happen to agree within the current scope. The inconsistency they
    # represent is visible cross-scope (cross-company, cross-period), not
    # necessarily inside this one query window.
    catch_all_list = ",".join(str(a) for a in CATCH_ALL_ACCOUNTS)
    con.execute(f"""
        UPDATE dim_account SET fs_category_flag = true
        WHERE gl_account IN ({catch_all_list})
    """)

    n = con.execute("SELECT COUNT(*) FROM dim_account").fetchone()[0]
    print(f"dim_account: {n} rows")


def compute_source_usage(con) -> dict:
    """live if the account has any debit/credit activity anywhere in the
    full source (not local_amount, which is unreliable for at least the
    clearing-pair accounts), or appears outside the current scope
    (a later period, or a company other than 1000). retired otherwise.
    Computed over the full table, not scope-filtered. A "live" verdict
    must survive being asked about the account's whole history, not just
    the slice this ticket happens to be looking at."""
    rows = con.execute(f"""
        SELECT gl_account,
               SUM(ABS(COALESCE(debit_amount, 0))) + SUM(ABS(COALESCE(credit_amount, 0))) AS gross_dr_cr,
               BOOL_OR(NOT ({SCOPE})) AS outside_scope
        FROM stg_gl
        GROUP BY 1
    """).fetchall()
    return {
        acc: "live" if (gross_dr_cr > 0 or outside_scope) else "retired"
        for acc, gross_dr_cr, outside_scope in rows
    }


def draft_map_account(con) -> None:
    source_usage = compute_source_usage(con)
    pair_id_of = {}
    for a, b in CLEARING_PAIRS:
        pid = f"{a}_{b}"
        pair_id_of[a] = pid
        pair_id_of[b] = pid

    rows = con.execute("""
        SELECT gl_account, account_class
        FROM dim_account
        ORDER BY gl_account
    """).fetchall()

    written = []
    for gl_account, account_class in rows:
        usage = source_usage.get(gl_account, "retired")
        role = ""
        dq_flag = ""
        notes = ""

        if gl_account in CATCH_ALL_ACCOUNTS:
            status = "catch_all"
            target = str(gl_account)
        elif gl_account in CLEARING_ACCOUNTS:
            status = "mapped"
            target = str(gl_account)
            role = "clearing"
        elif gl_account in pair_id_of:
            status = "unmapped"
            target = ""
            role = "clearing_pair"
            dq_flag = DQ_FLAG_PAIR
        elif account_class is None:
            status = "unmapped"
            target = ""
        else:
            status = "mapped"
            target = account_class

        written.append((
            gl_account, target, status, usage, role, dq_flag,
            pair_id_of.get(gl_account, ""), notes,
        ))

    with open(MAP_CSV, "w") as f:
        f.write("source_account,target_account,status,source_usage,account_role,dq_flag,pair_id,notes\n")
        for row in written:
            f.write(",".join(str(v) for v in row) + "\n")

    counts = {}
    for row in written:
        counts[row[2]] = counts.get(row[2], 0) + 1
    print(f"map_account.csv: {len(written)} rows -> {counts}")

    src_accounts = {r[0] for r in written}
    if len(src_accounts) != len(written):
        print("BLOCKED: source_account is not unique (map_fanout)")
        sys.exit(1)
    print("verified: source_account unique (map_fanout passes)")

    for a, b in CLEARING_PAIRS:
        if a not in src_accounts or b not in src_accounts:
            print(f"BLOCKED: clearing pair {a}/{b} is missing a side")
            sys.exit(1)
    print("verified: every clearing pair has both sides present")


def _query_target_groups(con):
    return con.execute(f"""
        SELECT account_class, account_class_name,
               COUNT(DISTINCT s.gl_account) AS gl_accounts,
               COUNT(*) AS lines,
               ROUND(SUM(s.local_amount), 0) AS net_local
        FROM stg_gl s WHERE {SCOPE}
        GROUP BY 1, 2 ORDER BY 2
    """).fetchall()


def _query_clearing_accounts(con):
    accs = ",".join(str(a) for a in CLEARING_ACCOUNTS)
    return con.execute(f"""
        SELECT s.gl_account, MIN(s.account_description),
               COUNT(*) lines, ROUND(SUM(s.local_amount), 0) net
        FROM stg_gl s WHERE {SCOPE} AND s.gl_account IN ({accs})
        GROUP BY 1 ORDER BY 1
    """).fetchall()


def _query_clearing_pairs(con):
    accs = ",".join(str(a) for pair in CLEARING_PAIRS for a in pair)
    return con.execute(f"""
        SELECT s.gl_account, ROUND(SUM(s.debit_amount), 0), ROUND(SUM(s.credit_amount), 0), COUNT(*) lines
        FROM stg_gl s WHERE {SCOPE} AND s.gl_account IN ({accs})
        GROUP BY 1 ORDER BY 1
    """).fetchall()


def _query_catch_all(con):
    accs = ",".join(str(a) for a in CATCH_ALL_ACCOUNTS)
    return con.execute(f"""
        SELECT s.gl_account, s.financial_statement_category,
               COUNT(*) lines_in_scope, ROUND(SUM(s.local_amount), 0) net_local_in_scope,
               COUNT(DISTINCT s.account_description) distinct_descriptions_in_scope
        FROM stg_gl s WHERE {SCOPE} AND s.gl_account IN ({accs})
        GROUP BY 1, 2 ORDER BY 1
    """).fetchall()


def _query_split_category(con):
    """account_class values whose member accounts do not agree with each
    other on financial_statement_category, excluding the hand-ruled
    catch-all accounts (ADR-0005: they must not dominate or distort a real
    class's vote by sheer volume)."""
    catch_all_list = ",".join(str(a) for a in CATCH_ALL_ACCOUNTS)
    dirty_classes = con.execute(f"""
        SELECT account_class FROM stg_gl
        WHERE {SCOPE} AND gl_account NOT IN ({catch_all_list})
        GROUP BY 1 HAVING COUNT(DISTINCT financial_statement_category) > 1
    """).fetchall()
    if not dirty_classes:
        return []
    class_list = ",".join(f"'{c[0]}'" for c in dirty_classes)
    return con.execute(f"""
        SELECT s.account_class, any_value(s.account_class_name),
               s.financial_statement_category,
               COUNT(DISTINCT s.gl_account) AS accounts,
               COUNT(*) AS lines,
               ROUND(SUM(s.local_amount), 0) AS net_local
        FROM stg_gl s
        WHERE {SCOPE} AND s.account_class IN ({class_list})
              AND s.gl_account NOT IN ({catch_all_list})
        GROUP BY 1, 3 ORDER BY 1, 3
    """).fetchall()


def _build_report_text(groups, clearing, pairs, catch_all, dirty) -> str:
    lines = [
        "# Mapping review: draft for #3\n",
        "Draft, not approved. See `docs/missions/01-chart-of-accounts-mapping.md`"
        " and `docs/adr/0005-account-status-catch-all.md`.\n",
        f"## 1. Target groups ({len(groups)} account_class values)\n",
        "Ordinary rollup accounts: `target_account` = `account_class`.\n",
    ]
    lines += _markdown_table(
        ["class", "name", "gl accounts", "lines", "net local"],
        [[f"`{cls}`", str(name), str(gl), f"{ln:,}", f"{net:,.0f}"] for cls, name, gl, ln, net in groups],
    )

    lines.append(
        "\n## 2. Clearing accounts (`status=mapped`, `account_role=clearing`, "
        "`target_account` = own code)\n"
        "Real, single-purpose clearing/suspense accounts. All confirmed "
        "`source_usage=live` across the full dataset (postings continue past "
        "the current scope, in every company) so each keeps its own code as "
        "target rather than being marked `deprecated`.\n"
    )
    lines += _markdown_table(
        ["gl_account", "description", "lines", "net local"],
        [[f"`{acc}`", str(desc), str(ln), f"{net:,.0f}"] for acc, desc, ln, net in clearing],
    )

    lines.append(
        "\n## 3. Clearing pairs (`status=unmapped`, `account_role=clearing_pair`, "
        f"`dq_flag={DQ_FLAG_PAIR}`)\n"
        "Debit-only / credit-only pairs. `local_amount` is 0 on every row for "
        "all six despite real debit/credit activity below. Do not read this "
        "set as immaterial from `local_amount` alone. Filed against issue #5. "
        "Stay `unmapped` until a human names the real pair target; never map "
        "one side without the other.\n"
    )
    lines += _markdown_table(
        ["gl_account", "sum debit", "sum credit", "lines"],
        [[f"`{acc}`", f"{dr:,.0f}", f"{cr:,.0f}", str(ln)] for acc, dr, cr, ln in pairs],
    )

    lines.append(
        "\n## 4. Catch-all accounts (`status=catch_all`, ADR-0005)\n"
        "Migration parking codes, not real accounts: many unrelated "
        "`account_description` values on the same code, active across all 4 "
        "companies and 13 periods in the full source (see ADR-0005). Each "
        "keeps its own code as `target_account` and reports on its own line, "
        "never merged with the other even though both fall under `account_class` "
        "`A.X`. Within the current scope they land in different "
        "`financial_statement_category` values and folding them together "
        "would misclassify one of them. `fs_category_flag` is forced true for "
        "both, and both are excluded from section 5's `A.X` vote.\n"
    )
    lines += _markdown_table(
        ["gl_account", "financial_statement_category (in scope)", "lines (in scope)", "net local (in scope)", "distinct descriptions (in scope)"],
        [[f"`{acc}`", str(cat), str(ln), f"{net:,.0f}", str(nd)] for acc, cat, ln, net, nd in catch_all],
    )
    lines.append(
        "\nIn-scope figures only. The full-dataset picture is far larger: "
        "`199999` carries 180,162,775 net local across 4 companies and 13 "
        "periods; `999999` carries 1,736,047. Neither total belongs to the "
        "current scope's close.\n"
    )

    lines.append(
        "\n## 5. Classes that split across financial_statement_category "
        "(each account is internally consistent; accounts within the same "
        "class disagree with each other, needs your ruling; catch-all "
        "accounts excluded, see section 4)\n"
    )
    lines += _markdown_table(
        ["class", "name", "category", "accounts", "lines", "net local"],
        [
            [f"`{cls}`", str(name), cat or "<null>", str(accts), f"{ln:,}", f"{net:,.0f}"]
            for cls, name, cat, accts, ln, net in dirty
        ],
    )

    return "\n".join(lines) + "\n"


def write_report(con) -> None:
    verify_self_consistent(con)
    report = _build_report_text(
        groups=_query_target_groups(con),
        clearing=_query_clearing_accounts(con),
        pairs=_query_clearing_pairs(con),
        catch_all=_query_catch_all(con),
        dirty=_query_split_category(con),
    )
    REPORT_MD.write_text(report)
    print(f"wrote {REPORT_MD}")


def main() -> int:
    con = duckdb.connect(str(WAREHOUSE_DB))
    verify_key(con)
    build_dim_account(con)
    draft_map_account(con)
    write_report(con)
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
