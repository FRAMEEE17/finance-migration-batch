"""Build dim_account and draft map_account.csv. Mission 01 / Ticket 3.

Scope: company 1000, FY2024 P01-P03. target_account = source account_class
(derived, not invented). status: unmapped (no class), deprecated (proposed,
suspense/clearing), mapped (everything else). Human approves before use.

Run: python src/build_mapping.py
"""

import sys

import duckdb  # type: ignore

from config import REPO_ROOT, WAREHOUSE_DB

SCOPE = "company_code = 1000 AND fiscal_year = 2024 AND fiscal_period IN (1,2,3)"
MAP_CSV = REPO_ROOT / "map_account.csv"
REPORT_MD = REPO_ROOT / "docs" / "mapping-review.md"

# Docs/missions/01: "suspense / clearing" is a business term, not a literal
# code value. This pattern is our own derivation of it, not something pinned
# in a doc, so it lives here as a named constant, not a magic string.
SUSPENSE_CLEARING_PATTERN = "%suspense%clearing%"


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
    financial_statement_category. dim_account assumes one category per
    account; if this ever fails, that assumption is wrong and nothing
    downstream (dim_account, the report) can be trusted."""
    bad = con.execute(f"""
        SELECT COUNT(*) FROM (
            SELECT gl_account FROM stg_gl WHERE {SCOPE}
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
    n = con.execute("SELECT COUNT(*) FROM dim_account").fetchone()[0]
    print(f"dim_account: {n} rows")


def draft_map_account(con) -> None:
    rows = con.execute(f"""
        SELECT
            gl_account AS source_account,
            account_class AS target_account,
            CASE
                WHEN account_class IS NULL THEN 'unmapped'
                WHEN account_class_name ILIKE '{SUSPENSE_CLEARING_PATTERN}' THEN 'deprecated'
                ELSE 'mapped'
            END AS status
        FROM dim_account
        ORDER BY gl_account
    """).fetchall()

    with open(MAP_CSV, "w") as f:
        f.write("source_account,target_account,status\n")
        for src, tgt, status in rows:
            f.write(f"{src},{tgt or ''},{status}\n")

    counts = {}
    for _, _, status in rows:
        counts[status] = counts.get(status, 0) + 1
    print(f"map_account.csv: {len(rows)} rows -> {counts}")

    src_accounts = {r[0] for r in rows}
    if len(src_accounts) != len(rows):
        print("BLOCKED: source_account is not unique (map_fanout)")
        sys.exit(1)
    print("verified: source_account unique (map_fanout passes)")


def _query_target_groups(con):
    return con.execute(f"""
        SELECT account_class, account_class_name,
               COUNT(DISTINCT s.gl_account) AS gl_accounts,
               COUNT(*) AS lines,
               ROUND(SUM(s.local_amount), 0) AS net_local
        FROM stg_gl s WHERE {SCOPE}
        GROUP BY 1, 2 ORDER BY 2
    """).fetchall()


def _query_unmapped(con):
    return con.execute(f"""
        SELECT s.gl_account, MIN(s.account_description),
               COUNT(*) lines, ROUND(SUM(s.local_amount), 0) net
        FROM stg_gl s WHERE {SCOPE} AND s.account_class IS NULL
        GROUP BY 1 ORDER BY 1
    """).fetchall()


def _query_deprecated(con):
    return con.execute(f"""
        SELECT s.gl_account, MIN(s.account_description),
               COUNT(*) lines, ROUND(SUM(s.local_amount), 0) net
        FROM stg_gl s WHERE {SCOPE} AND s.account_class_name ILIKE '{SUSPENSE_CLEARING_PATTERN}'
        GROUP BY 1 ORDER BY 1
    """).fetchall()


def _query_split_category(con):
    """account_class values whose member accounts do not agree with each
    other on financial_statement_category (each account is internally
    consistent; verify_self_consistent already guarantees that)."""
    dirty_classes = con.execute(f"""
        SELECT account_class FROM stg_gl WHERE {SCOPE}
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
        GROUP BY 1, 3 ORDER BY 1, 3
    """).fetchall()


def _build_report_text(groups, unmapped, deprecated, dirty) -> str:
    lines = [
        "# Mapping review: draft for #3\n",
        "Draft, not approved. See `docs/missions/01-chart-of-accounts-mapping.md`.\n",
        f"## 1. Target groups ({len(groups)} account_class values)\n",
    ]
    lines += _markdown_table(
        ["class", "name", "gl accounts", "lines", "net local"],
        [[f"`{cls}`", str(name), str(gl), f"{ln:,}", f"{net:,.0f}"] for cls, name, gl, ln, net in groups],
    )

    lines.append("\n## 2. Unmapped (no account_class, needs your ruling)\n")
    lines += _markdown_table(
        ["gl_account", "description", "lines", "net local"],
        [[f"`{acc}`", str(desc), str(ln), f"{net:,.0f}"] for acc, desc, ln, net in unmapped],
    )

    lines.append("\n## 3. Deprecated proposal (suspense / clearing, needs your ruling)\n")
    lines += _markdown_table(
        ["gl_account", "description", "lines", "net local"],
        [[f"`{acc}`", str(desc), str(ln), f"{net:,.0f}"] for acc, desc, ln, net in deprecated],
    )

    lines.append(
        "\n## 4. Classes that split across financial_statement_category "
        "(each account is internally consistent; accounts within the same "
        "class disagree with each other, needs your ruling)\n"
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
        unmapped=_query_unmapped(con),
        deprecated=_query_deprecated(con),
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
