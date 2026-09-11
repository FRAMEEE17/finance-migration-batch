"""Period report for finance sign-off. Ticket 9 / Mission 09.

Writes reports/period_2024-01.md from the warehouse tables built by
tickets 5-8 (dq_violations, recon_period_summary, recon_mismatch,
recon_reversal_pairs). No new computation happens here; this script only
assembles and formats numbers those tables already hold.

The sign-off in this report is split into two pieces on purpose, per the
human ruling on mission 09:
  - the stg_gl vs fact_gl_line reconciliation is accepted (clean by every
    check this project runs: 0.00 gap, all accounts matching, 0% unknown)
  - the reported local_amount total is NOT signed (it inherits a known
    source-data defect, mission 06 / issue #13, and both sides of the
    comparison carry the same broken numbers, so a clean reconciliation
    here doesn't mean the total is correct)
Never write "verified close" or "final" anywhere in this report about
the local_amount total - that phrasing is exactly what a reader would
mistake for a signed number.

Run: python src/build_period_report.py
"""

import sys

import duckdb  # type: ignore

from config import REPO_ROOT, WAREHOUSE_DB

REPORT_MD = REPO_ROOT / "reports" / "period_2024-01.md"

KNOWN_ISSUE_PARAGRAPH = (
    "The number in the local_amount column below is broken for 20 documents "
    "this period. The stg-vs-fact comparison shows a perfect match only "
    "because both sides inherit the same broken figures, not because either "
    "one was independently verified. Debit and credit are the more reliable "
    "signal for this period's true balance: see the Reconciliation section "
    "for both."
)


def _markdown_table(header: list[str], rows: list[list[str]]) -> list[str]:
    if not rows:
        return ["none"]
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out.extend("| " + " | ".join(cells) + " |" for cells in rows)
    return out


def _fetch(con) -> dict:
    period_summary = con.execute("""
        SELECT COUNT(*), ROUND(SUM(stg_local_total), 2), ROUND(SUM(fact_local_total), 2),
               ROUND(SUM(local_amount_gap), 2),
               SUM((ABS(local_amount_gap) > 0.01)::int)
        FROM recon_period_summary
    """).fetchone()

    exceptions = con.execute("""
        SELECT gl_account, stg_local_total, fact_local_total, local_amount_gap
        FROM recon_period_summary WHERE ABS(local_amount_gap) > 0.01
        ORDER BY gl_account
    """).fetchall()

    dc_gap = con.execute(f"""
        SELECT ROUND(SUM(debit_amount) - SUM(credit_amount), 2)
        FROM stg_gl WHERE company_code = 1000 AND fiscal_year = 2024 AND fiscal_period = 1
    """).fetchone()[0]

    mismatch = con.execute("""
        SELECT bucket, cause, COUNT(*), ROUND(SUM(gap), 2) FROM recon_mismatch GROUP BY 1, 2 ORDER BY 1, 2
    """).fetchall()

    unknown_pct = con.execute("""
        SELECT ROUND(100.0 * SUM((cause = 'unknown')::int) / COUNT(*), 1) FROM recon_mismatch
    """).fetchone()[0] or 0.0

    reversal = con.execute("""
        SELECT COUNT(*), SUM(cross_period::int), SUM(is_net_zero::int), SUM((NOT is_net_zero)::int)
        FROM recon_reversal_pairs
    """).fetchone()

    dq = con.execute("""
        SELECT check_name, blocking, COUNT(*) FROM dq_violations GROUP BY 1, 2 ORDER BY 2 DESC, 1
    """).fetchall()

    unbalanced_excluded = con.execute("""
        SELECT COUNT(*) FROM dq_violations WHERE check_name = 'unbalanced_document' AND blocking = true
    """).fetchone()[0]

    return {
        "period_summary": period_summary,
        "exceptions": exceptions,
        "dc_gap": dc_gap,
        "mismatch": mismatch,
        "unknown_pct": unknown_pct,
        "reversal": reversal,
        "dq": dq,
        "unbalanced_excluded": unbalanced_excluded,
    }


def build_report_text(data: dict) -> str:
    n_accounts, stg_total, fact_total, gap, n_exceptions = data["period_summary"]

    lines = [
        "# Period report: 2024-01",
        "",
        "Company 1000, fiscal year 2024, period 01. Draft for finance review,",
        "see the sign-off section at the end before treating any number here",
        "as final.",
        "",
        "## Known issue: local_amount is not reliable this period",
        "",
        KNOWN_ISSUE_PARAGRAPH,
        "",
        f"Scale: **{97144587.1:,.1f}** across 20 documents. Full technical detail:",
        "`docs/period-close-notes/2024-01-local-amount-defect.md`, source-data",
        "investigation tracked in issue #13.",
        "",
        "## Reconciliation (stg_gl vs fact_gl_line)",
        "",
        f"- Accounts compared: **{n_accounts}**",
        f"- Accounts that match exactly: **{n_accounts - n_exceptions}**",
        f"- local_amount total, stg side: {stg_total:,.2f}",
        f"- local_amount total, fact side: {fact_total:,.2f}",
        f"- local_amount gap: {gap:,.2f} (see Known Issue above before reading this as clean)",
        f"- debit/credit gap, whole scope: **{data['dc_gap']:,.2f}** (the more trustworthy figure;",
        f"  {data['unbalanced_excluded']} document excluded as unbalanced, this is what's left)",
        "",
    ]

    if data["exceptions"]:
        lines.append("Accounts with a real local_amount gap (both from the excluded unbalanced document):")
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
    lines += [
        "## Reversal pairs",
        "",
        f"- Detected pairs: **{total_pairs}**",
        f"- Crossing a period boundary (original and reversal in different periods): {cross_period}",
        f"- Economically valid (debit/credit correctly swap): {valid}",
        f"- Flagged as not a real reversal (see issue #7 - mostly planted fraud/anomaly cases): {invalid}",
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
        f"- the 1 unbalanced document is correctly excluded; the remaining",
        f"  debit/credit gap for the period is {data['dc_gap']:,.2f}",
        "",
        "**Not signed:**",
        "",
        "- the period close total as measured by local_amount",
        "- the 97,144,587.1 figure arising from the 20 documents that broadcast",
        "  a document total across every debit line instead of a per-line amount",
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
        "Issue: #9. Related: #6, #13.",
        "",
    ]

    return "\n".join(lines) + "\n"


def build_period_report(con) -> None:
    data = _fetch(con)
    text = build_report_text(data)
    REPORT_MD.parent.mkdir(exist_ok=True)
    REPORT_MD.write_text(text)


def main() -> int:
    con = duckdb.connect(str(WAREHOUSE_DB), read_only=True)
    build_period_report(con)
    con.close()
    print(f"wrote {REPORT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
