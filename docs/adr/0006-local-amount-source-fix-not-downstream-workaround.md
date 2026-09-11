# local_amount: the AB source system regenerates, this pipeline doesn't

**Status:** accepted

`docs/missions/13-local-amount-source-investigation.md` found the real
cause of the `local_amount` broadcast defect: `source = 'AB'`, not high
line count. Every `source = 'AB'` document in the full source file
(1,123 of them, all 4 companies, both fiscal years) has this defect;
zero exceptions. Dataset-wide it's 1,132 documents and
`$9,522,749,609.33` net `local_amount`, roughly a fifth of total debit
activity by dollar volume.

## Decision

The `AB` source system regenerates `local_amount` per line, from that
line's own converted amount, not the document's total broadcast across
every debit line. This pipeline does not build a permanent downstream
substitute for the broken column.

Reasoning:

- Reports, reversal-pair detection, and account totals would each end
  up computing `local_amount` a different way if downstream owned the
  fix - one true number split into several approximations.
- A broadcast document's `local_amount` doesn't even change sign
  correctly on a reversal (the reversal side would need its own
  guessed correction). A downstream loader guessing at what the number
  should have been hides the defect instead of surfacing it.
- Finance can sign the reconciliation (`stg_gl` vs `fact_gl_line`
  matches) but not the `local_amount` total, because the number in the
  warehouse would still be a downstream reconstruction of something
  the source never actually computed correctly - not a verified figure.
- If `AB` fixes itself later and downstream also silently fixed it in
  parallel, a reload could double-correct or silently overwrite a
  now-correct source value with a stale local guess, with nothing
  forcing that state to be noticed.

## What downstream may still do

A temporary, clearly-separate column is allowed while `AB` hasn't
regenerated yet - for example `local_amount_line`, computed from that
line's own `debit_amount`/`credit_amount`. Rules if this gets built:

- Never overwrites or aliases `stg_gl.local_amount`. The original,
  broken, source value stays visible and queryable exactly as
  received.
- Any period report using it states plainly that the figure is
  reconstructed by this pipeline, not the source's own number - the
  same "not signed" framing already used for `local_amount` itself,
  not upgraded to a signed figure just because it's a nicer-looking
  reconstruction.
- Not built by this mission. Mission 13 is investigation only; this
  ADR records the rule for whoever builds it, if it gets built before
  `AB` regenerates.

## Acceptance criteria for a regenerated file from AB

Before treating a new source drop as fixing this defect:

- No `source = 'AB'` document has more than one distinct `local_amount`
  value across its debit lines when those lines have different
  `debit_amount` values (the exact broadcast signature found here).
- A reversal of an `AB` document correctly swaps debit/credit and
  reverses `local_amount` per line, not just at the document total.
- Checked across all 4 companies and both fiscal years, not just the
  company 1000 / FY2024 P01-P03 scope this pipeline currently loads.

## Open question, not settled by this ADR

A related but distinct pattern exists: rows where `local_amount = 0`
despite a nonzero `debit_amount` or `credit_amount`. Dataset-wide this
is 931 rows (580 of them company 1000 / FY2024), 58 documents inside
this pipeline's P01-P03 scope. It correlates with `source IN
('automated', 'adjustment')`, not `source = 'AB'`, and has zero overlap
with reversal documents (`reference LIKE 'REV-%'`). This is a different
defect shape from the broadcast pattern this ADR covers - conflating
the two would misattribute both. Whether it belongs inside issue #13's
scope or as its own ticket is not decided here; see mission 13's Retro
for the open question recorded back to the issue.