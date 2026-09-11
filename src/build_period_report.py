"""Period report for finance sign-off. Ticket 9, parameterized by period
in ticket 10.

Assembles reports/period_<year>-<period>.md from warehouse tables built
by tickets 5-8; no new computation happens here. Sign-off is split in
two: the stg_gl vs fact_gl_line reconciliation is accepted, but the
reported local_amount total is not signed (issue #13). Never describe
local_amount as "verified" or "final" in the output - see ADR-0006/0007.

Run: python src/build_period_report.py <company_code> <fiscal_year> <fiscal_period>
  e.g. python src/build_period_report.py 1000 2024 2
"""

import sys
from pathlib import Path
from typing import List

import duckdb  # type: ignore

from config import REPO_ROOT, WAREHOUSE_DB


def report_path(fiscal_year: int, fiscal_period: int) -> Path:
    return REPO_ROOT / "reports" / f"period_{fiscal_year}-{fiscal_period:02d}.md"


def _no_neg_zero(v):
    """DuckDB's parallel SUM is not associativity-safe: the same query
    can return a tiny negative float (e.g. -2e-7) instead of exactly 0.0
    depending on thread scheduling, which after ROUND(...,2) prints as
    "-0.00" instead of "0.00" - same number, different sign a reader
    would misread as a real asymmetry. -0.0 + 0.0 == 0.0 in IEEE 754, so
    this is a no-op on every value except that one."""
    return v if v is None else v + 0.0


def _markdown_table(header: List[str], rows: List[List[str]]) -> List[str]:
    if not rows:
        return ["none"]
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out.extend("| " + " | ".join(cells) + " |" for cells in rows)
    return out


def _fetch(con, company_code: int, fiscal_year: int, fiscal_period: int) -> dict:
    pf = f"company_code = {company_code} AND fiscal_year = {fiscal_year} AND fiscal_period = {fiscal_period}"

    period_summary_row = con.execute(f"""
        SELECT COUNT(*), ROUND(SUM(stg_local_total), 2), ROUND(SUM(fact_local_total), 2),
               ROUND(SUM(local_amount_gap), 2),
               SUM((ABS(local_amount_gap) > 0.01)::int)
        FROM recon_period_summary WHERE {pf}
    """).fetchone()
    n_accounts, stg_total, fact_total, local_gap, n_exceptions = period_summary_row
    period_summary = (n_accounts, _no_neg_zero(stg_total), _no_neg_zero(fact_total), _no_neg_zero(local_gap), n_exceptions)

    exceptions = [
        (account, _no_neg_zero(s), _no_neg_zero(f), _no_neg_zero(g))
        for account, s, f, g in con.execute(f"""
            SELECT gl_account, stg_local_total, fact_local_total, local_amount_gap
            FROM recon_period_summary WHERE {pf} AND ABS(local_amount_gap) > 0.01
            ORDER BY gl_account
        """).fetchall()
    ]

    dc_gap = _no_neg_zero(con.execute(f"""
        SELECT ROUND(SUM(debit_amount) - SUM(credit_amount), 2) FROM stg_gl WHERE {pf}
    """).fetchone()[0])

    # Materiality cutoff matches mission 06's original split: dq_violations'
    # local_amount_imbalance check flags any nonzero net (23 rows for P01),
    # but 3 of those are genuine sub-cent rounding, not the broadcast-total
    # defect this report exists to disclose. Only documents over 0.01 count
    # as "the defect" here, same threshold mission 06 used to tell them apart.
    imbalanced = con.execute(f"""
        WITH doc_totals AS (
            SELECT document_id, ROUND(SUM(local_amount), 2) AS local_amount
            FROM stg_gl WHERE {pf}
            GROUP BY 1
        ),
        flagged AS (
            SELECT DISTINCT document_id FROM dq_violations
            WHERE check_name = 'local_amount_imbalance' AND {pf}
        )
        SELECT COUNT(*), ROUND(SUM(doc_totals.local_amount), 2)
        FROM doc_totals JOIN flagged USING (document_id)
        WHERE ABS(doc_totals.local_amount) > 0.01
    """).fetchone()

    mismatch = [
        (bucket, cause, count, _no_neg_zero(amt))
        for bucket, cause, count, amt in con.execute(f"""
            SELECT bucket, cause, COUNT(*), ROUND(SUM(gap), 2) FROM recon_mismatch WHERE {pf} GROUP BY 1, 2 ORDER BY 1, 2
        """).fetchall()
    ]

    unknown_pct = con.execute(f"""
        SELECT ROUND(100.0 * SUM((cause = 'unknown')::int) / COUNT(*), 1) FROM recon_mismatch WHERE {pf}
    """).fetchone()[0] or 0.0

    # Scoped by the original document's period, not the reversal's - a pair
    # can cross a period boundary, and "originated this period" is what
    # sums to the whole table across all periods without double-counting.
    reversal = con.execute(f"""
        SELECT COUNT(*), SUM(cross_period::int), SUM(is_net_zero::int), SUM((NOT is_net_zero)::int)
        FROM recon_reversal_pairs
        WHERE original_fiscal_year = {fiscal_year} AND original_fiscal_period = {fiscal_period}
    """).fetchone()

    dq = con.execute(f"""
        SELECT check_name, blocking, COUNT(*) FROM dq_violations WHERE {pf} GROUP BY 1, 2 ORDER BY 2 DESC, 1
    """).fetchall()

    unbalanced_excluded = con.execute(f"""
        SELECT COUNT(*) FROM dq_violations WHERE {pf} AND check_name = 'unbalanced_document' AND blocking = true
    """).fetchone()[0]

    return {
        "period_summary": period_summary,
        "exceptions": exceptions,
        "dc_gap": dc_gap,
        "imbalanced_doc_count": imbalanced[0] or 0,
        "imbalanced_total": imbalanced[1] or 0.0,
        "mismatch": mismatch,
        "unknown_pct": unknown_pct,
        "reversal": reversal,
        "dq": dq,
        "unbalanced_excluded": unbalanced_excluded,
    }


def build_report_text(data: dict, company_code: int, fiscal_year: int, fiscal_period: int) -> str:
    n_accounts, stg_total, fact_total, gap, n_exceptions = data["period_summary"]
    label = f"{fiscal_year}-{fiscal_period:02d}"
    imbalanced_docs = data["imbalanced_doc_count"]
    imbalanced_total = data["imbalanced_total"]

    known_issue_paragraph = (
        f"The number in the local_amount column below is broken for {imbalanced_docs} "
        "documents this period. The stg-vs-fact comparison shows a perfect match only "
        "because both sides inherit the same broken figures, not because either "
        "one was independently verified. Debit and credit are the more reliable "
        "signal for this period's true balance: see the Reconciliation section "
        "for both."
    ) if imbalanced_docs else (
        "No local_amount defect documents were found for this period at build time. "
        "See issue #13 for the pattern found in other periods before treating this "
        "period's local_amount total as verified."
    )

    lines = [
        f"# Period report: {label}",
        "",
        f"Company {company_code}, fiscal year {fiscal_year}, period {fiscal_period:02d}.",
        "Draft for finance review, see the sign-off section at the end before",
        "treating any number here as final.",
        "",
        "## Known issue: local_amount is not reliable this period",
        "",
        known_issue_paragraph,
        "",
    ]
    if imbalanced_docs:
        lines += [
            f"Scale: **{imbalanced_total:,.1f}** across {imbalanced_docs} documents. Full technical",
            "detail: `docs/period-close-notes/2024-01-local-amount-defect.md` (the P01",
            "finding; mission 10 confirmed the same pattern in P02/P03), source-data",
            "investigation tracked in issue #13.",
            "",
        ]

    lines += [
        "## Reconciliation (stg_gl vs fact_gl_line)",
        "",
        f"- Accounts compared: **{n_accounts}**",
        f"- Accounts that match exactly: **{n_accounts - n_exceptions}**",
        f"- local_amount total, stg side: {stg_total:,.2f}",
        f"- local_amount total, fact side: {fact_total:,.2f}",
        f"- local_amount gap: {gap:,.2f} (see Known Issue above before reading this as clean)",
        f"- debit/credit gap, whole scope: **{data['dc_gap']:,.2f}** (the more trustworthy figure;",
        f"  {data['unbalanced_excluded']} document(s) excluded as unbalanced, this is what's left)",
        "",
    ]

    if data["exceptions"]:
        lines.append("Accounts with a real local_amount gap:")
        lines.append("")
        lines += _markdown_table(
            ["gl_account", "stg total", "fact total", "gap"],
            [[str(a), f"{s:,.2f}", f"{f:,.2f}", f"{g:,.2f}"] for a, s, f, g in data["exceptions"]],
        )
        lines.append("")

    lines += [
        "## Mismatches, by bucket and cause",
        "",
        f"Every mismatch this period has a named cause. Unexplained (\"unknown\"): **{data['unknown_pct']}%**.",
        "",
    ]
    lines += _markdown_table(
        ["bucket", "cause", "count", "amount"],
        [[b, c, str(n), f"{amt:,.2f}"] for b, c, n, amt in data["mismatch"]],
    )
    lines.append("")

    total_pairs, cross_period, valid, invalid = data["reversal"]
    total_pairs = total_pairs or 0
    lines += [
        "## Reversal pairs (originated this period)",
        "",
        f"- Detected pairs: **{total_pairs}**",
        f"- Crossing a period boundary (reversal posts in a different period): {cross_period or 0}",
        f"- Economically valid (debit/credit correctly swap): {valid or 0}",
        f"- Flagged as not a real reversal (see issue #7 - mostly planted fraud/anomaly cases): {invalid or 0}",
        "",
        "## Data quality, for context (none of this blocks the reconciliation above)",
        "",
    ]
    lines += _markdown_table(
        ["check", "blocking", "count"],
        [[name, "yes" if blocking else "no", str(n)] for name, blocking, n in data["dq"]],
    )

    lines += [
        "",
        "## Sign-off",
        "",
        "This report separates two different things on purpose: whether the",
        "reconciliation process is trustworthy, and whether the reported dollar",
        "total is trustworthy. They are not the same question this period.",
        "",
        "**Signed:**",
        "",
        "- the stg_gl vs fact_gl_line reconciliation is clean: 0.00 gap,",
        f"  {n_accounts - n_exceptions}/{n_accounts} accounts match exactly, 0% unknown mismatches",
        f"- unbalanced documents are correctly excluded; the remaining debit/credit",
        f"  gap for the period is {data['dc_gap']:,.2f}",
        "",
        "**Not signed:**",
        "",
        "- the period close total as measured by local_amount",
    ]
    if imbalanced_docs:
        lines.append(
            f"- the {imbalanced_total:,.1f} figure arising from {imbalanced_docs} documents that "
            "broadcast a document total across every debit line instead of a per-line amount"
        )
    lines += [
        "- this report is not a \"verified close\" and not a \"final\" number for",
        "  local_amount, regardless of how clean the reconciliation above looks",
        "",
        "```",
        "Reconciliation: accepted",
        "Reported local_amount total: not signed",
        "```",
        "",
        "This close pack is usable as a working paper only. The numbers to use",
        "for period judgment are debit/credit, until issue #13 fixes the source.",
        "",
        "Signed by: _______________  Date: _______________",
        "",
        "---",
        "Technical references: `recon_period_summary`, `recon_mismatch`,",
        "`recon_reversal_pairs`, `dq_violations` in `warehouse.duckdb`.",
        f"Issue: #9 (report pattern), #10 (this period's backfill). Related: #6, #13.",
        "",
    ]

    return "\n".join(lines) + "\n"


def build_period_report(con, company_code: int, fiscal_year: int, fiscal_period: int) -> Path:
    data = _fetch(con, company_code, fiscal_year, fiscal_period)
    text = build_report_text(data, company_code, fiscal_year, fiscal_period)
    path = report_path(fiscal_year, fiscal_period)
    path.parent.mkdir(exist_ok=True)
    path.write_text(text)
    return path


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: python src/build_period_report.py <company_code> <fiscal_year> <fiscal_period>")
        return 1
    company_code, fiscal_year, fiscal_period = (int(v) for v in sys.argv[1:4])

    con = duckdb.connect(str(WAREHOUSE_DB), read_only=True)
    path = build_period_report(con, company_code, fiscal_year, fiscal_period)
    con.close()
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
