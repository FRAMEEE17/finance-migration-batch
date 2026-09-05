# Requirements: Finance Migration + Reconciliation

## 1. Business goal

Move the legacy GL (SAP-style extract) into a new warehouse so the finance team
can close a fiscal period against the new numbers and trust them.

- **Who uses it:** finance controller and internal audit; analysts consume the
  cleaned GL tables downstream.
- **What they decide from it:** whether a period's new-system total matches the
  legacy total, and if not, which documents cause the gap and why.
- **If the data is wrong or late:** the period cannot be signed off; audit loses
  the trail from legacy to new; downstream analyst tables carry the error.

## 2. Personas

- **Finance controller.** Signs off the period. Needs legacy vs new totals per
  account and per period, and a named reason for every difference.
- **Internal auditor.** Needs to trace any new-system row back to its legacy
  source, and evidence that cancelled / unbalanced / opening entries were handled.
- **Junior DE.** Runs and maintains the pipeline. Needs a runbook and clear
  rules for what is publishable.
- **Analyst waiting for the morning table.** Needs the cleaned GL to land on
  time and to be stable when re-run.

## 3. In scope

- GL header / line ingestion
- Chart of accounts
- Account mapping (legacy → target)
- Data quality checks
- Reconciliation per period and per document
- Idempotent period load
- Runbook

## 4. Out of scope

- Polished dashboards
- Real-time / streaming
- Spark / Databricks in the first pass
- Editing source data
- Inventing or adjusting amounts to make a total tie

## 5. Definition of done

Scope: `company_code = 1000`, periods `(2024,01)`, `(2024,02)`, `(2024,03)`.
Reconciliation baseline is `stg_gl` (raw, as-received) vs `fact_gl_line`
(mapped, deduped, DQ-checked). See `docs/definitions.md`. All of the
following:

- Re-loading the same period yields the same totals and row counts.
- A `dq_violations` output exists.
- Reconciliation exists at both account level and document level, checked to
  0.01 tolerance (gaps ≤ 0.01 auto-labeled `rounding`).
- Every difference over 0.01 has a named cause, never `unknown`.
- `OPENING_BALANCE`, `CL`, and `is_post_close` documents are not mixed into
  in-period totals (post-close gets its own reported bucket, not deletion).
- `is_fraud` / `is_anomaly` rows are never filtered out; they surface in the
  mismatch report if they cause a difference.
- Reversal pairs (`reference` = `REV-...`, `header_text` = "Reversal of ...")
  are detected, linked, and reported, never deleted.
- Unbalanced documents (`debit_amount − credit_amount ≠ 0`) are never
  published.
- `map_account.csv` is approved by hand before any reconcile run; no account
  code is invented; `source_account` is unique (`map_fanout` blocks the load
  otherwise).
- Duplicate grain (`company_code + document_id + line_number + fiscal_year +
  fiscal_period` appearing twice) blocks publish (`duplicate_source`). No
  auto-pick of a "latest" row.
- Every mismatch carries exactly one bucket (`missing_in_fact`,
  `missing_in_stg`, `amount_changed`, `intentionally_excluded`) and one cause
  from the fixed list in `docs/definitions.md`. `unknown` causes must stay
  under 20% of the period's mismatches or the report cannot be signed.
- A signed-off deliverable exists per period: `reports/period_2024-01.md`
  (totals by account, mismatch counts by bucket, cause table).
- A runbook lets someone run one period end to end in 20 minutes.

## 6. Non-goals of Step 0

- No data generation yet.
- No loader code yet.

---

This file is ready to convert to PDF with:
`pandoc docs/requirements.md -o docs/requirements.pdf`
(Do not render the PDF until pandoc is installed. Do not create a placeholder PDF.)
