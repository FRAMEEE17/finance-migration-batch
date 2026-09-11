# reports/period_*.md is a working paper, not the finance sign-off artifact

**Status:** accepted

An enterprise close doesn't run on Markdown. It runs on three separate
layers, each with its own owner and its own artifact:

1. **Subledger / accounting system** (SAP, Oracle, NetSuite, Dynamics).
   The official balance lives here. This repo doesn't have one - it
   reconciles a source extract, it doesn't replace a general ledger.
2. **Warehouse + quality gate.** What this repo builds: staging, fact,
   recon, `dq_violations`. The output of this layer is tables and a
   pass/fail state, not a document.
3. **What a human reads.** Close and audit work from a locked-formula
   spreadsheet or a PDF; executives read a BI dashboard; the data
   team's own evidence trail is a working paper (Markdown, notebooks,
   ADRs).

`reports/period_<year>-<period>.md` has always lived correctly in layer
3, but the wrong shelf on it: `docs/business-rules.md` and
`docs/requirements.md` both called it "the signed-off deliverable,"
and `docs/architecture.md`'s diagram labeled it "signed by finance."
Neither claim is true of a Markdown file with a blank signature line at
the bottom - it's a working paper, real evidence of what was checked
and what wasn't, not the artifact an accounting department calls a
closed period.

## Decision

Reports keep being generated exactly as they are now - the "Known
issue" paragraph before the reconciliation numbers, the split sign-off
block, the debit/credit-not-local_amount guidance. Nothing about
`build_period_report.py`'s content changes. What changes is what the
project calls it, and what sits underneath it.

**`period_signoff`**, a new table, one row per `(company_code,
fiscal_year, fiscal_period)`, is the actual machine-readable close
state - the thing a BI tool or a PDF generator would read, not the
Markdown file's prose. Columns: `recon_status` (`accepted` once the
reconciliation is clean, matching the report's own "Signed" section),
`local_amount_status` (`not_signed` while issue #13 is open, `signed`
once it's closed and a report confirms local_amount matches source),
the same headline figures the report already prints (`accounts_compared`,
`accounts_matched`, `dc_gap`, `imbalanced_doc_count`,
`imbalanced_total`, `unknown_mismatch_pct`), `report_path`, and
`generated_at`. Built by `build_period_report.py` from the same `data`
dict the report text already comes from - one computation, two
outputs, never two sources of truth that could drift apart.

Nothing beyond this table is built now. Explicitly deferred, in order:

- A 1-2 page PDF from a template, with a real signature line, a link
  back to the warehouse and the tracking issue - the artifact a human
  would actually sign. Reads from `period_signoff`, not from parsing
  the Markdown.
- A BI dashboard (Power BI or equivalent) reading `period_signoff`.
  **Not started before this table exists and carries real status
  values** - a dashboard binding directly to `local_amount` would show
  a big number with no visible caveat, exactly the failure mode the
  Markdown report's own "Known issue" section exists to prevent.

## What this doesn't change

- `docs/period-close-notes/*.md`, the ADRs, and the notebooks stay
  working papers. That was always the right shelf for them.
- The report's own content and structure - this ADR renames what layer
  it sits in, it doesn't touch what it says.
- Issue #13 is still what has to close before `local_amount_status` can
  ever read `signed`. This table makes that state queryable, it doesn't
  change the condition.