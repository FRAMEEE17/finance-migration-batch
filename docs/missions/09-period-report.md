# Mission 09: Period report for finance sign-off

- **Signal:** issue #9, `manual` label (same label as issue #1 - a
  human-facing deliverable, not a purely technical one). No `Blocked by:`
  line; reads `recon_period_summary` (#6), `recon_mismatch` (#8),
  `recon_reversal_pairs` (#7), `dq_violations` (#5), all closed.
- **Confidence:** high on assembling the numbers, every one already
  built and cross-checked by an earlier mission. Low on the sign-off
  question itself, which is exactly the point of this ticket.
- **Type:** request with the project's central judgement call embedded
  in it. `docs/definitions.md`: "**Closed period**: A period whose
  `reports/period_YYYY-PP.md` a human has accepted." This mission writes
  the document; it does not get to decide whether it's accepted.
- **Decision:** act, bounded. Build `reports/period_2024-01.md` with
  every number issue #9 asks for, script-generated like every other
  report in this repo (`docs/mapping-review.md` pattern). Surface the
  known `local_amount` defect prominently, ahead of the totals, not as a
  footnote. Do not decide whether the period is signable - that's
  finance's call, framed clearly in Human approvals below.

## Rules that apply

> "Write `reports/period_2024-01.md` for finance to read and sign. It
> should stand on its own. Someone in finance reads it without opening a
> query." (issue #9)

> "**'Done' for every task:** a period total (`stg_gl` vs `fact_gl_line`,
> per account, checked to 0.01 tolerance), a count of documents that
> don't match, and a primary cause for every gap > 0.01 (not one bucket
> of `unknown`). The signed-off deliverable is `reports/period_<period>.md`."
> (docs/business-rules.md)

> "**Closed period**: A period whose `reports/period_YYYY-PP.md` a human
> has accepted. It is not a database state, a green pipeline, or a
> loaded table." (CONTEXT.md)

> "The period cannot be closed using `local_amount` as it stands. The
> discrepancy is 97,144,587.1, coming from 20 documents."
> (docs/period-close-notes/2024-01-local-amount-defect.md, mission 06)

## Exploration

`notebooks/09-period-report.ipynb`. Every number the report needs is
already built; this pass consolidates and cross-checks them one more
time before anything goes into a finance-facing document.

- **Headline reconciliation**: 502 accounts, stg total = fact total =
  `97,144,587.12`, gap = `0.00`. Read on its own, this says the period
  reconciles perfectly. It doesn't say the number is trustworthy: 20 of
  those documents carry the `local_amount` defect mission 06 found (a
  document total broadcast across every debit line), inherited
  identically by both `stg_gl` and `fact_gl_line` - which is exactly why
  the gap is zero. **This is the report's central risk**: a reader who
  sees "gap = 0.00" without the caveat is told something false.
- **Mismatch bucket + cause, count and amount** (issue #9's explicit
  ask): `opening_balance` 17 rows / net -0.01 (one 17-line brought-forward
  document, large individual lines that net to ~$0 together, not a
  residual worth chasing), `post_close` 200 rows / net 578,374.47,
  `unbalanced_document` 2 rows / net 0.00.
- **Reversal pairs** (issue #9's explicit ask for a count): 1,025 pairs,
  326 cross-period, 940 valid, 85 flagged planted anomalies (mission 07).
- **Data-quality context**: `catch_all_account` 70, `local_amount_imbalance`
  23, `unmapped_account` 15, `unbalanced_document` 1 (blocking).

Nothing here is a new finding. The open question this mission actually
has to resolve isn't a number, it's whether a period that's clean by
every check this project runs, but rests on a known, unresolved
`local_amount` defect the checks can't see, is one finance should sign.

## Desired outcomes

- `reports/period_2024-01.md`: plain language, no query/table-name
  jargon in the main narrative (footnote references only), written for
  someone who won't open a SQL client. Structure:
  1. A prominent, first-section disclosure of the `local_amount` defect
     (drawn from `docs/period-close-notes/2024-01-local-amount-defect.md`),
     before any total is shown, not after.
  2. Reconciliation summary: stg vs fact totals, gap, account-match count.
  3. Mismatch bucket + cause table (count and amount).
  4. Reversal-pair summary (count, cross-period count, flagged-anomaly count).
  5. Data-quality context (non-blocking findings, for completeness).
  6. A sign-off section: named decision to make (see Human approvals),
     blank line for who signed and when, explicit reference to issue #9.
- `src/build_period_report.py`: generates the report from the warehouse
  tables, same pattern as `src/build_mapping.py` generating
  `docs/mapping-review.md`. Re-running it must reproduce the same file
  byte-for-byte given unchanged data.

## Deterministic checks

- [ ] Every number in `reports/period_2024-01.md` matches its source
      table exactly (no rounding drift, no hand-typed figures) - checked
      by parsing the generated file back and comparing to a fresh query,
      not by eyeballing it once at generation time.
- [ ] The `local_amount` defect disclosure appears before the
      reconciliation totals in the file (byte offset comparison), not
      just present somewhere in the document.
- [ ] Re-running `src/build_period_report.py` twice produces an
      identical file (same idempotency bar as every other report in
      this project).
- [ ] The report contains no unexplained internal table/column names
      (`recon_mismatch`, `stg_gl`, etc.) outside of an explicit
      "technical references" footer, since issue #9 requires it to stand
      alone for a non-technical reader.

## Non-deterministic checks

| Check | Who | How an agent verifies |
|---|---|---|
| the plain-language framing of the `local_amount` defect doesn't understate or overstate it relative to mission 06/`docs/period-close-notes/2024-01-local-amount-defect.md`'s own wording | you | agent shows the two texts side by side |
| the report reads clearly to someone without SQL/warehouse context | you | no automated proxy for this; a fresh read is the only real check |

## Non-goals

- Not deciding whether the period is signable. That decision belongs to
  the "Before the output is used" gate below, made once by you, not
  inferred from whether the checks are green.
- Not fixing the `local_amount` defect. Still #13's territory.
- Not writing P02/P03's reports. Those need #10 (backfill) first.
- Not changing `recon_period_summary`/`recon_mismatch`/
  `recon_reversal_pairs`'s underlying logic. This mission reads them,
  doesn't recompute or second-guess what #6/#7/#8 already established.

## Human approvals

**Before build:**

- report structure and section order above, `local_amount` disclosure
  goes first, ahead of any total
- `src/build_period_report.py` follows the existing script-generates-report
  pattern (`src/build_mapping.py`), not a hand-written document

**Before the output is used (sign-off = closing #9):**

- **the actual decision this ticket exists for**: does finance sign
  `reports/period_2024-01.md` given the known `local_amount` defect?
  Candidates, not a recommendation:
  1. Sign with an explicit caveat: the reconciliation (stg vs fact) is
     accepted as clean; the reported dollar total is explicitly flagged
     as unverified pending #13, not represented as final.
  2. Withhold sign-off until #13 resolves or a corrected total exists,
     even though every automated check in this project passes.
  3. Something else - a partial sign-off, a different scope carve-out,
     etc.
- once a decision is made, closing issue #9 with that decision recorded
  in the comment is what "closed period" means for 2024-01
  (docs/definitions.md)

## Retro

Filled after the mission closes.
