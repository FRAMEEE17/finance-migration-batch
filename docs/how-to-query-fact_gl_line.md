# How to query fact_gl_line

For anyone pulling numbers for analysis or a downstream table - not
the recon/data team, not finance sign-off. Read `fact_gl_line_ready`,
not `fact_gl_line` directly: it's the same data, filtered to periods
that are actually safe to use.

## Grain

One row is one document line - `company_code + document_id +
line_number + fiscal_year + fiscal_period`. Not one row per account,
not one row per document. `GROUP BY` whatever you need; don't assume
one row already represents a whole document or account.

## Which table to read

`fact_gl_line_ready`, not `fact_gl_line`. The view is
`fact_gl_line` joined to `period_signoff`, filtered to periods where
`recon_status = 'accepted'` - a period isn't in the view at all until
its reconciliation is clean. It carries every column `fact_gl_line`
has, plus:

- `recon_status` - always `accepted` in this view, by construction
- `local_amount_status` - `not_signed` or `signed`. Read this before
  touching `local_amount`, every time.
- `is_period_movement` - `true` unless the row is
  `is_opening_balance`, `is_closing_entry`, or `is_post_close`. A
  period's "what happened this period" total excludes all three
  (`docs/business-rules.md`): opening balances are brought-forward,
  closing entries and post-close activity aren't part of the in-period
  close.

## Which columns are safe to sum for a period total

- **`debit_amount` / `credit_amount`: always safe.** This is the
  figure this project trusts for period judgment, regardless of
  `local_amount_status`.
- **`local_amount`: only when `local_amount_status = 'signed'`.**
  Every period in this project is `not_signed` right now (issue #13,
  source-data defect - see `docs/adr/0006-local-amount-source-fix-not-downstream-workaround.md`
  and `docs/adr/0007-local-amount-zero-clearing-pairs-by-design.md`).
  `local_amount` is still in the view - it isn't hidden - but it is
  not the column this doc tells you to `SUM`. Check
  `local_amount_status` per row before aggregating it; don't assume
  the whole view shares one status forever.

## Correct example

```sql
-- Period total, the figure to trust regardless of local_amount_status
SELECT fiscal_year, fiscal_period,
       ROUND(SUM(debit_amount) - SUM(credit_amount), 2) AS period_total
FROM fact_gl_line_ready
WHERE is_period_movement
GROUP BY 1, 2
ORDER BY 1, 2;
```

Returns `0.00` for P03 and `-0.00` for P01/P02, run against this
warehouse - the ledger balances on debit/credit everywhere except the
one already-excluded unbalanced document per period, which never
reaches `fact_gl_line` in the first place. The `-0.00` is a known
DuckDB floating-point display quirk (parallel `SUM` isn't
associativity-safe, so a true-zero result can print with a stray minus
sign - see mission 10's retro), not a real asymmetry; either sign here
means the same thing, balanced.

## Wrong example - the trap this doc exists to prevent

```sql
-- DO NOT DO THIS while local_amount_status = 'not_signed'
SELECT document_id, ROUND(SUM(local_amount), 2) AS broken_total
FROM fact_gl_line_ready
WHERE document_id = '0a121d1e-7334-81f7-2608-9bb9a6e55fab'
GROUP BY 1;
```

Returns **`41,646,671.85`** - real, run against this warehouse, not
made up. That document has 37 lines and a source system (`AB`) with a
confirmed defect (mission 13): the document's grand total gets
repeated on every debit line instead of each line's own amount, so
summing `local_amount` multiplies the real figure by roughly the
number of lines. The correct figure for the same document:

```sql
SELECT document_id, ROUND(SUM(debit_amount) - SUM(credit_amount), 2) AS correct_total
FROM fact_gl_line_ready
WHERE document_id = '0a121d1e-7334-81f7-2608-9bb9a6e55fab'
GROUP BY 1;
```

Returns **`0.00`** - the document is balanced, same as any other. The
`local_amount` query doesn't just round differently, it isn't
measuring the same thing at all.

## What this view is not

Not a dashboard. Not a sign-off artifact - `period_signoff` and
`reports/controller_pack_*.md` are the only places a close status gets
recorded (ADR-0008). Not a fix for issue #13 - `local_amount` stays
broken in the source until that closes; this view exists so a
consumer doesn't have to discover that the hard way.
