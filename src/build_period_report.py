"""Period report and sign-off state. Ticket 9, parameterized by period
in ticket 10, split into working paper vs. machine-readable state in
ADR-0008.

Assembles reports/period_<year>-<period>.md - a working paper, not the
artifact an accounting department calls a closed period (ADR-0008) -
and writes the same figures into period_signoff, one row per period,
for whatever reads close status downstream (a future PDF, a BI
dashboard). Both come from one _fetch() call; never two sources of
truth that could drift apart.

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


def controller_pack_path(fiscal_year: int, fiscal_period: int) -> Path:
    return REPO_ROOT / "reports" / f"controller_pack_{fiscal_year}-{fiscal_period:02d}.md"


def exceptions_path(fiscal_year: int, fiscal_period: int) -> Path:
    return REPO_ROOT / "reports" / f"exceptions_{fiscal_year}-{fiscal_period:02d}.md"


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

    # Raw (unrounded) drives the accept/reject decision; the 20% rule in
    # docs/definitions.md compares the actual percentage, not a display
    # rounding of it - a real 19.96% must not fail just because it prints
    # as 20.0%. `unknown_pct` stays rounded for the report/controller-pack
    # text; `unknown_pct_raw` is what recon_status is decided on.
    unknown_pct_raw = con.execute(f"""
        SELECT 100.0 * SUM((cause = 'unknown')::int) / COUNT(*) FROM recon_mismatch WHERE {pf}
    """).fetchone()[0] or 0.0
    unknown_pct = round(unknown_pct_raw, 1)

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

    unbalanced_document_ids = [
        r[0] for r in con.execute(f"""
            SELECT DISTINCT document_id FROM dq_violations
            WHERE {pf} AND check_name = 'unbalanced_document' AND blocking = true
            ORDER BY 1
        """).fetchall()
    ]

    return {
        "period_summary": period_summary,
        "exceptions": exceptions,
        "dc_gap": dc_gap,
        "imbalanced_doc_count": imbalanced[0] or 0,
        "imbalanced_total": imbalanced[1] or 0.0,
        "mismatch": mismatch,
        "unknown_pct": unknown_pct,
        "unknown_pct_raw": unknown_pct_raw,
        "reversal": reversal,
        "dq": dq,
        "unbalanced_excluded": unbalanced_excluded,
        "unbalanced_document_ids": unbalanced_document_ids,
    }


def _fetch_exceptions(con, company_code: int, fiscal_year: int, fiscal_period: int) -> dict:
    """The 4 material categories for the exception appendix. Each query
    reuses an already-established predicate from an earlier mission
    (materiality > 0.01 from mission 06, source='AB' from mission 13,
    local_amount_expected=false from ADR-0007, NOT is_net_zero from
    mission 07) rather than inventing a new threshold here."""
    pf = f"company_code = {company_code} AND fiscal_year = {fiscal_year} AND fiscal_period = {fiscal_period}"

    broadcast_docs = con.execute(f"""
        WITH doc_totals AS (
            SELECT document_id, ANY_VALUE(source) AS source, ANY_VALUE(document_type) AS document_type,
                   COUNT(*) AS n_lines, ROUND(SUM(local_amount), 2) AS net_local_amount
            FROM stg_gl WHERE {pf}
            GROUP BY 1
        ),
        flagged AS (
            SELECT DISTINCT document_id FROM dq_violations
            WHERE check_name = 'local_amount_imbalance' AND {pf}
        )
        SELECT d.document_id, d.source, d.document_type, d.n_lines, d.net_local_amount
        FROM doc_totals d JOIN flagged USING (document_id)
        WHERE ABS(d.net_local_amount) > 0.01
        ORDER BY ABS(d.net_local_amount) DESC
    """).fetchall()

    catch_all = con.execute(f"""
        SELECT s.gl_account, COUNT(*) AS n_lines, ROUND(SUM(s.local_amount), 2) AS net_local
        FROM stg_gl s
        JOIN map_account m ON m.source_account = s.gl_account AND m.status = 'catch_all'
        WHERE {pf}
        GROUP BY 1 ORDER BY 1
    """).fetchall()

    clearing_pairs = con.execute(f"""
        SELECT s.gl_account, m.pair_id, COUNT(*) AS n_lines,
               ROUND(SUM(s.debit_amount), 2) AS sum_debit, ROUND(SUM(s.credit_amount), 2) AS sum_credit
        FROM stg_gl s
        JOIN map_account m ON m.source_account = s.gl_account AND m.local_amount_expected = false
        WHERE {pf}
        GROUP BY 1, 2 ORDER BY 1
    """).fetchall()

    text_only_reversals = con.execute(f"""
        SELECT original_document_id, reversal_document_id, any_flagged,
               original_debit_total, original_credit_total,
               reversal_debit_total, reversal_credit_total
        FROM recon_reversal_pairs
        WHERE NOT is_net_zero
          AND original_fiscal_year = {fiscal_year} AND original_fiscal_period = {fiscal_period}
        ORDER BY original_document_id
    """).fetchall()

    return {
        "broadcast_docs": broadcast_docs,
        "catch_all": catch_all,
        "clearing_pairs": clearing_pairs,
        "text_only_reversals": text_only_reversals,
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
        "Working paper (data engineering / internal audit) - not the controller",
        f"sign-off artifact. See `reports/controller_pack_{fiscal_year}-{fiscal_period:02d}.md`",
        "for that, and the sign-off section at the end before treating any",
        "number here as final.",
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
        "Source: `recon_period_summary` in `warehouse.duckdb`.",
        "",
    ]

    if data["unbalanced_document_ids"]:
        lines += [
            "Documents excluded as unbalanced (in `stg_gl`, never reach `fact_gl_line`,",
            "logged in `dq_violations` with `check_name='unbalanced_document'`):",
            "",
        ]
        lines += _markdown_table(["document_id"], [[d] for d in data["unbalanced_document_ids"]])
        lines.append("")

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
        "Source: `recon_mismatch` in `warehouse.duckdb`.",
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
        "Source: `recon_reversal_pairs` in `warehouse.duckdb`.",
        "",
        "## Data quality, for context (none of this blocks the reconciliation above)",
        "",
        "Source: `dq_violations` in `warehouse.duckdb`.",
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
        "Machine-readable state: `period_signoff` in `warehouse.duckdb`, one row",
        "for this period. Controller-facing pack:",
        f"`reports/controller_pack_{fiscal_year}-{fiscal_period:02d}.md`.",
        "Exception detail: `reports/exceptions_{}-{:02d}.md`.".format(fiscal_year, fiscal_period),
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


def build_controller_pack_text(data: dict, company_code: int, fiscal_year: int, fiscal_period: int) -> str:
    """1-2 pages, plain language, risk before totals. A controller signs
    or withholds from this file alone - technical detail lives in the
    working paper and exception appendix, referenced by footnote only."""
    n_accounts, _, _, _, n_exceptions = data["period_summary"]
    label = f"{fiscal_year}-{fiscal_period:02d}"
    imbalanced_docs = data["imbalanced_doc_count"]
    recon_status = "accepted" if data["unknown_pct_raw"] <= 20.0 else "rejected"

    lines = [
        f"# Controller pack: {label}",
        "",
        f"Company {company_code}, period {fiscal_period:02d}. For sign-off review.",
        "",
        "## Risk this period",
        "",
    ]
    if imbalanced_docs:
        lines += [
            f"{imbalanced_docs} documents this period report a currency total that "
            "cannot be trusted[^1]. The figure normally used to close a period is "
            "broken for those documents; debit and credit totals are not affected "
            "and remain reliable. This is a known, tracked issue, not new this "
            "period.",
            "",
        ]
    else:
        lines += [
            "No documents with the known currency-total defect were found this "
            "period at build time. See the open tracking item below before "
            "treating that total as verified.",
            "",
        ]

    lines += [
        "## Decision",
        "",
        f"- **Reconciliation:** {recon_status}",
        "- **Reported currency total:** not signed",
        "",
        f"- Documents compared[^2]: **{n_accounts}**, matched exactly: **{n_accounts - n_exceptions}**",
        f"- Debit/credit gap (the figure to use for this period's judgment): "
        f"**{data['dc_gap']:,.2f}**",
        "",
        "The reconciliation decision and the currency-total decision are not the",
        "same question. A clean reconciliation does not mean the currency total",
        "is correct - both sides of that comparison inherit the same defect.",
        "",
        "## Status at a glance",
        "",
    ]
    lines += _markdown_table(
        ["recon_status", "local_amount_status", "dc_gap", "defect doc count"],
        [[recon_status, "not_signed", f"{data['dc_gap']:,.2f}", str(imbalanced_docs)]],
    )
    lines += [
        "",
        "## Still open",
        "",
        "Issue #13 (source-data defect, not this pipeline's territory) has to",
        "close before the currency total above can be signed. Full detail is in",
        "the working paper and exception appendix for this period, not repeated",
        "here.",
        "",
        "## Sign-off",
        "",
        "Reconciliation reviewed and accepted by:",
        "",
        "Signed by: _______________  Date: _______________",
        "",
        "Currency total: **not signed this period.**",
        "",
        "---",
        "[^1]: The defect: a document's grand total is repeated on every debit",
        "line instead of that line's own amount. `local_amount` in the",
        "warehouse; `stg_gl`/`fact_gl_line` are the raw and modeled tables.",
        "[^2]: Compared in `recon_period_summary`, one row per account per",
        "period, in `warehouse.duckdb`.",
        "",
    ]

    return "\n".join(lines) + "\n"


def build_exceptions_text(data: dict, exc: dict, company_code: int, fiscal_year: int, fiscal_period: int) -> str:
    """Material items only - the 4 categories issue #15 named. Backs the
    working paper's summary numbers with document/account-level detail;
    never lists sub-cent noise."""
    label = f"{fiscal_year}-{fiscal_period:02d}"
    non_ab = [d for d in exc["broadcast_docs"] if d[1] != "AB"]
    root_cause_line = (
        "Root cause: `source='AB'` (mission 13)."
        if not non_ab else
        f"Root cause: `source='AB'` for {len(exc['broadcast_docs']) - len(non_ab)} of these "
        f"(mission 13); the rest is unrelated sub-cent rounding, kept here only because it "
        "shares the same materiality-filtered total the working paper quotes."
    )
    lines = [
        f"# Exception appendix: {label}",
        "",
        f"Company {company_code}, period {fiscal_period:02d}. Material items only.",
        "",
        "## 1. local_amount broadcast documents",
        "",
        "Same document set and total as the working paper's Known Issue section",
        f"(materiality > 0.01): **{data['imbalanced_doc_count']}** documents, "
        f"**{data['imbalanced_total']:,.1f}**. {root_cause_line}",
        "",
    ]
    lines += _markdown_table(
        ["document_id", "source", "document_type", "lines", "net local_amount"],
        [[d, s, dt, str(n), f"{amt:,.2f}"] for d, s, dt, n, amt in exc["broadcast_docs"]],
    )

    lines += [
        "",
        "## 2. catch_all accounts (ADR-0005)",
        "",
        "Migration parking codes, not real accounts. Listed for visibility, not",
        "as a defect - `map_account.csv status='catch_all'`.",
        "",
    ]
    lines += _markdown_table(
        ["gl_account", "lines this period", "net local_amount"],
        [[str(a), str(n), f"{amt:,.2f}"] for a, n, amt in exc["catch_all"]],
    )

    lines += [
        "",
        "## 3. Designed zero-local clearing pairs (ADR-0007)",
        "",
        "`local_amount` is 0 on every row of these accounts by design, not a",
        "defect - do not read activity here as a new local_amount problem.",
        "",
    ]
    lines += _markdown_table(
        ["gl_account", "pair_id", "lines this period", "sum debit", "sum credit"],
        [[str(a), p, str(n), f"{dr:,.2f}", f"{cr:,.2f}"] for a, p, n, dr, cr in exc["clearing_pairs"]],
    )

    lines += [
        "",
        "## 4. Text-only reversal mismatches (mission 07)",
        "",
        "The reversal text convention matched (`REV-...` reference), but the",
        "amounts don't correspond to the claimed original. Flagged, never",
        "filtered - most carry an `is_fraud`/`is_anomaly` flag.",
        "",
    ]
    lines += _markdown_table(
        ["original_document_id", "reversal_document_id", "fraud/anomaly flagged"],
        [[o, r, "yes" if flagged else "no"] for o, r, flagged, *_ in exc["text_only_reversals"]],
    )
    lines.append("")

    return "\n".join(lines) + "\n"


def ensure_period_signoff_table(con) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS period_signoff (
            company_code BIGINT, fiscal_year BIGINT, fiscal_period BIGINT,
            recon_status VARCHAR, local_amount_status VARCHAR,
            accounts_compared BIGINT, accounts_matched BIGINT,
            dc_gap DOUBLE, unknown_mismatch_pct DOUBLE,
            imbalanced_doc_count BIGINT, imbalanced_total DOUBLE,
            report_path VARCHAR, controller_pack_path VARCHAR, exceptions_path VARCHAR,
            generated_at TIMESTAMP
        )
    """)


def write_period_signoff(
    con, data: dict, company_code: int, fiscal_year: int, fiscal_period: int,
    report: Path, controller_pack: Path, exceptions: Path,
) -> None:
    """The machine-readable half of a period's close state (ADR-0008) -
    same data dict the report text comes from, so the two can never
    disagree. recon_status follows the same <20% unknown threshold that
    blocks sign-off project-wide (docs/business-rules.md); local_amount
    is a human call tied to issue #13, not something this function can
    derive, so it stays not_signed until that issue closes and a human
    updates it."""
    ensure_period_signoff_table(con)
    n_accounts, _, _, _, n_exceptions = data["period_summary"]
    recon_status = "accepted" if data["unknown_pct_raw"] <= 20.0 else "blocked"

    pf = f"company_code = {company_code} AND fiscal_year = {fiscal_year} AND fiscal_period = {fiscal_period}"
    con.execute(f"DELETE FROM period_signoff WHERE {pf}")
    con.execute(
        """
        INSERT INTO period_signoff VALUES
        (?, ?, ?, ?, 'not_signed', ?, ?, ?, ?, ?, ?, ?, ?, ?, now())
        """,
        [
            company_code, fiscal_year, fiscal_period, recon_status,
            n_accounts, n_accounts - n_exceptions, data["dc_gap"], data["unknown_pct"],
            data["imbalanced_doc_count"], data["imbalanced_total"],
            str(report), str(controller_pack), str(exceptions),
        ],
    )


def build_period_report(con, company_code: int, fiscal_year: int, fiscal_period: int) -> Path:
    """Writes only reports/period_<year>-<period>.md - the working paper.
    Read-only-safe - a rebuild is a pure function of what's already in
    the warehouse, and checks.py's idempotency check relies on that."""
    data = _fetch(con, company_code, fiscal_year, fiscal_period)
    text = build_report_text(data, company_code, fiscal_year, fiscal_period)
    path = report_path(fiscal_year, fiscal_period)
    path.parent.mkdir(exist_ok=True)
    path.write_text(text)
    return path


def build_controller_pack(con, company_code: int, fiscal_year: int, fiscal_period: int) -> Path:
    """Writes reports/controller_pack_<year>-<period>.md. Read-only-safe,
    same reason as build_period_report()."""
    data = _fetch(con, company_code, fiscal_year, fiscal_period)
    text = build_controller_pack_text(data, company_code, fiscal_year, fiscal_period)
    path = controller_pack_path(fiscal_year, fiscal_period)
    path.parent.mkdir(exist_ok=True)
    path.write_text(text)
    return path


def build_exceptions_appendix(con, company_code: int, fiscal_year: int, fiscal_period: int) -> Path:
    """Writes reports/exceptions_<year>-<period>.md. Read-only-safe, same
    reason as build_period_report()."""
    data = _fetch(con, company_code, fiscal_year, fiscal_period)
    exc = _fetch_exceptions(con, company_code, fiscal_year, fiscal_period)
    text = build_exceptions_text(data, exc, company_code, fiscal_year, fiscal_period)
    path = exceptions_path(fiscal_year, fiscal_period)
    path.parent.mkdir(exist_ok=True)
    path.write_text(text)
    return path


def run(con, company_code: int, fiscal_year: int, fiscal_period: int) -> dict:
    """Mission 20: the one entry point this file didn't already have.
    Every other script in the pipeline separates a callable core from
    main()'s argv handling; this one's core was actually 5 sequential
    calls sharing one _fetch() result. This is that sequence, minus the
    argv parsing and connection open/close - the same thing main() below
    runs, and what the Airflow DAG task calls directly. Nothing inside
    build_period_report/build_controller_pack/build_exceptions_appendix/
    write_period_signoff changed."""
    report = build_period_report(con, company_code, fiscal_year, fiscal_period)
    controller_pack = build_controller_pack(con, company_code, fiscal_year, fiscal_period)
    exceptions = build_exceptions_appendix(con, company_code, fiscal_year, fiscal_period)
    data = _fetch(con, company_code, fiscal_year, fiscal_period)
    write_period_signoff(con, data, company_code, fiscal_year, fiscal_period, report, controller_pack, exceptions)
    return {"report": report, "controller_pack": controller_pack, "exceptions": exceptions}


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: python src/build_period_report.py <company_code> <fiscal_year> <fiscal_period>")
        return 1
    company_code, fiscal_year, fiscal_period = (int(v) for v in sys.argv[1:4])

    con = duckdb.connect(str(WAREHOUSE_DB))
    report = build_period_report(con, company_code, fiscal_year, fiscal_period)
    controller_pack = build_controller_pack(con, company_code, fiscal_year, fiscal_period)
    exceptions = build_exceptions_appendix(con, company_code, fiscal_year, fiscal_period)
    data = _fetch(con, company_code, fiscal_year, fiscal_period)
    write_period_signoff(con, data, company_code, fiscal_year, fiscal_period, report, controller_pack, exceptions)
    con.close()
    print(f"wrote {report}\nwrote {controller_pack}\nwrote {exceptions}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
