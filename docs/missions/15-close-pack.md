# Mission 15: final period-close pack

- **Signal:** issue #15, no blocker.
- **Confidence:** high. Every underlying number already exists in the
  warehouse (missions 6-10, 13, 14); this mission splits and re-labels
  presentation, it computes nothing new except document-level detail
  queries for the exception appendix.
- **Type:** build, fully specified by the issue - no open design
  question to grill on, the audience split and the 4 style rules are
  given.
- **Decision:** act. Extend `src/build_period_report.py` (same
  script-generates-report pattern, ADR-0008) to emit 3 files per period
  instead of 1, plus update `period_signoff` to record where the
  controller pack and working paper each live.

## Rules that apply

> "Split the output into three artifacts... Status first, totals
> second... The pack never collapses process-clean and amount-true
> into one green light." (issue #15)

> "Rebuilds must not present overwritten drafts as the signed copy."
> (issue #15)

> ADR-0008: `reports/period_*.md` is a working paper, not the artifact
> an accounting department calls a closed period.

## Exploration

Confirmed every figure the 3 artifacts need is already computable from
existing tables, no new SQL logic beyond document-level detail queries
for the appendix:

- **Controller pack**: `period_signoff` already carries `recon_status`,
  `local_amount_status`, `dc_gap`, `imbalanced_doc_count` - the exact 4
  fields the issue's one-page status table asks for.
- **Working paper**: already has bucket/cause, dq counts, reversal
  counts. Missing: an explicit excluded-unbalanced-document list (the
  ID, not just a count) and a line naming which warehouse table backs
  each section.
- **Exception appendix, 4 categories, checked against real data**:
  - Local_amount broadcast documents: `stg_gl` rows with `source='AB'`
    (root cause, mission 13) joined to the same materiality-filtered
    (`ABS(net) > 0.01`) document list `build_period_report.py`'s
    `imbalanced` query already computes - just needs `document_id`
    added to the SELECT instead of only aggregates.
  - Catch_all accounts: `map_account.csv status='catch_all'`
    (`199999`, `999999`, ADR-0005), activity for the period from
    `stg_gl` directly.
  - Designed zero-local clearing pairs: the 8 accounts with
    `local_amount_expected=false` in `map_account.csv` (ADR-0007) -
    shown so a reader never mistakes a $0 `local_amount` on these for
    a new defect.
  - Text-only reversal mismatches: `recon_reversal_pairs WHERE NOT
    is_net_zero`, scoped to pairs whose original posted this period
    (same scoping rule mission 09/10 already established for the
    reversal section).
- **Rebuild-overwrite risk** (issue's explicit style rule): confirmed
  `report_path()`/`controller_pack_path()`/`exceptions_path()` all
  write to a fixed filename per period with no draft/final
  distinction in the filename itself - a rebuild silently replaces
  whatever was there. `period_signoff.generated_at` already timestamps
  every write; the mitigation is procedural (git history +
  `generated_at`), not a new file-naming scheme, since this project's
  established idempotency proof already treats "the file is the
  current state, git is the history" as the working model
  (`period_report_idempotent_rebuild` and the mission 10 backfill
  proof both rely on exactly this).

## Desired outcomes

- `reports/controller_pack_<year>-<period>.md`: risk-first, plain
  language, footnoted technical terms, the two split decisions, a
  4-column status table, signature lines, what's blocked.
- `reports/period_<year>-<period>.md` (existing working paper):
  extended with the excluded-unbalanced-document list and a
  warehouse-object annotation per section. Content otherwise
  unchanged - this file already does real technical work.
- `reports/exceptions_<year>-<period>.md`: the 4 material categories,
  document/account-level detail, nothing sub-cent.
- `period_signoff` gains `controller_pack_path` and
  `exceptions_path` columns alongside the existing `report_path`.

## Deterministic checks

- [x] All 3 files exist for all 3 periods (9 files total).
      `close_pack_files_exist`.
- [x] Controller pack never contains the strings "verified" or
      "final" describing local_amount (same rule as the working
      paper, now checked on a second file).
      `controller_pack_never_claims_verified_or_final`.
- [x] Controller pack's risk/known-issue section appears before its
      first total, same byte-offset check pattern as the working
      paper's existing check. `controller_pack_risk_before_decision`.
- [x] The two decisions (reconciliation, local_amount) never collapse
      into one status. `controller_pack_shows_split_decision`.
- [x] Exception appendix's local_amount broadcast section is exactly
      the same document set and total the working paper's own
      materiality-filtered figure already reports - two files, one
      number, checked to agree.
      `exceptions_broadcast_total_matches_working_paper`.
- [x] `period_signoff` row carries all 3 file paths.
      `period_signoff_carries_all_three_paths`.
- [x] Idempotent rebuild: all 3 files identical byte-for-byte on a
      second run with unchanged warehouse state.
      `close_pack_idempotent_rebuild` (controller pack + exceptions;
      the working paper's own idempotency check already existed).

## Non-deterministic checks

| Check | Who | How an agent verifies |
|---|---|---|
| a controller can actually sign or withhold in under two minutes from the controller pack alone | you | agent can't time a human reading it; you judge the pack cold |

## Non-goals

- Not building a PDF renderer or a BI dashboard. The controller pack
  is written so `pandoc` could render it (same convention
  `docs/requirements.md` already uses), not rendered here.
- Not changing what any existing figure means - this mission
  re-presents already-computed numbers, it doesn't recompute the
  underlying reconciliation.
- Not adding sign-off workflow (who's authorized to flip
  `local_amount_status`, an approval UI) - flagged as a gap in
  conversation, not this mission's scope.

## Human approvals

**Before build:** none needed - the issue itself already resolved
every design question a grilling pass would normally raise.

**Before the output is used:** you read a controller pack cold and
confirm the two-minute bar; comment "approved" on #15.

## Retro

Every figure the 3 artifacts needed already existed somewhere in the
warehouse before this mission started - the actual work was splitting
one data dict (`_fetch`) into three audiences, not computing anything
new, except the exception appendix's document-level detail queries
(the working paper only ever needed aggregates).

One accuracy bug caught before it shipped: the exception appendix's
"local_amount broadcast documents" section initially claimed "Root
cause: source='AB'" unconditionally, copied from the working paper's
materiality-filtered document set - but that set includes 1 document
per some periods (P01 specifically) that isn't `source='AB'` at all,
the already-known sub-cent rounding case from mission 06. Fixed by
computing the AB-vs-other split at write time instead of assuming the
whole set shares one cause; the sentence now says "for 19 of these"
when there's an exception, not "for all of these."

`build_period_report()`'s read-only-safe boundary from ADR-0008 held
without needing a redesign: `build_controller_pack()` and
`build_exceptions_appendix()` both followed the same pattern (fetch,
render, write text - no DB write), so `checks.py`'s new idempotency
check could call them on the read-only connection exactly like the
existing one does.

`period_signoff`'s schema changed (2 new columns). Since the table is
fully derived from warehouse state and `warehouse.duckdb` is gitignored,
the fix was dropping and letting `CREATE TABLE IF NOT EXISTS` recreate
it, not a migration - worth remembering if a real migration is ever
needed on a table that isn't fully derivable from source, this pattern
wouldn't be safe there.

Not built, per the issue's own non-goals: PDF rendering, a BI
dashboard, or a sign-off workflow (who's authorized to flip
`local_amount_status`). The controller pack is written plainly enough
that `pandoc` could render it, matching the convention
`docs/requirements.md` already uses, but nothing renders it here.
