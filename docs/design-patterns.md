# Design patterns

The patterns this project uses, from Bartosz Konieczny, *Data Engineering
Design Patterns* (O'Reilly, 2025). Each entry: the problem the book states,
how this project applies it, and where we differ.

## Ingestion

### Full Loader (ch. Data Ingestion)

- **Book:** a source with no last-updated attribute, so you cannot detect
  changed rows. Extract and load the whole thing, no transformation.
- **Us:** `src/load_stg.py`. The source has no CDC column, so `stg_gl` is a
  full `CREATE OR REPLACE` copy of the parquet.
- **Delta:** the book's motivating case is a small, slowly-evolving
  dimension reloaded often. Ours is a one-time migration extract. Same
  mechanism (EL, no transform), different cadence.

## Idempotency

### Data Overwrite (ch. Idempotency)

- **Book:** a job that backfills generates duplicates because there is no
  metadata layer to clean first. Use a native replacement command
  (Spark save mode, Delta `replaceWhere`).
- **Us:** the period loader (Ticket 4) replaces the whole period every run.
  In DuckDB that is `DELETE` the period then `INSERT`, or partition
  overwrite.

### Transactional Writer (ch. Idempotency)

- **Book:** a job on spot capacity gets nodes pulled mid-write, leaving
  partial data visible. Wrap the write in a transaction so consumers only
  see committed data.
- **Us:** the period load runs in one transaction. A failure partway
  through leaves the old period intact, never a half-loaded one.

### Keyed Idempotency (ch. Idempotency), partial

- **Book:** generate a stable key from immutable attributes so a retried
  write lands once.
- **Us:** we use the grain key (`company_code + doc_id + line_no +
  fiscal_period`) to *detect* duplicates, not to dedup on write. See
  "not Windowed Deduplicator" below.

## Error management

### Dead-Letter (ch. Error Management)

- **Book:** unprocessable records (poison pills) stop the job. Save them
  elsewhere for later investigation and keep the pipeline running.
- **Us:** `dq_violations`. Rows that fail a blocking check land there with
  check name, document, line, period, detail. Nothing is dropped silently.

### Windowed Deduplicator (ch. Error Management), deliberately not used

- **Book:** dedup within the current batch or a time window to guarantee
  exactly-once.
- **Us:** the source has no `updated_at` / version column, so there is no
  correct way to pick which copy of a duplicate grain is latest. We block
  (`duplicate_source`) and let a human decide, rather than auto-pick. See
  ADR and `docs/definitions.md`.

## Data quality

### Audit-Write-Audit-Publish (ch. Data Quality)

- **Book:** add assertions to the data flow that stop execution if the
  dataset does not meet expectations, before anything is published.
- **Us:** the quality gate (Ticket 5). Blocking audits
  (`unbalanced_document`, `duplicate_source`, `map_fanout`, null key) run
  before anything reaches `fact_gl_line`.

### Offline Observer (ch. Data Observability)

- **Book:** monitor dataset properties (value distribution, null counts)
  in a component that does not block the main pipeline.
- **Us:** the non-blocking findings. `local_amount_imbalance` and
  `unmapped_account` are reported, counted, and tracked, but they do not
  stop a load.

### Constraints Enforcer / Schema Compatibility Enforcer (ch. Data Quality)

- **Book:** validate entries against predefined rules; validate that a
  schema change does not break downstream.
- **Us:** `src/load_stg.py` asserts `stg_gl` matches the source schema
  column for column. The doc_type catalog and `map_account` status are the
  value-level constraints.

## Enrichment

### Static Joiner (ch. Data Value)

- **Book:** bring an at-rest reference dataset to an activity dataset by a
  shared key.
- **Us:** `map_account.csv` (a static, hand-approved reference) joined to
  GL lines on `gl_account` to produce `dim_account` and the mapped
  `fact_gl_line`.

### Slowly Changing Dimension, deliberately not used (ch. Data Modeling)

- **Book:** a dimension's attributes change over time; a fact should keep
  reflecting the dimension value that was true when the fact happened, not
  silently pick up a later change. SCD Type 2 solves this with an
  effective-dated dimension table and a live join.
- **Us:** `dim_account` is rebuilt from `map_account.csv` on every load
  (Type 1, overwrite), but that isn't the mechanism protecting a closed
  period. `src/load_fact.py`'s period loader joins `map_account` once, at
  load time, and writes `target_account` and `map_status` directly onto
  each `fact_gl_line` row - a denormalized snapshot, not a live reference.
  If `map_account.csv` changes later, an already-loaded period's rows keep
  the mapping they were closed under; nothing re-derives them until that
  period is reloaded on purpose.
- **Delta:** same problem SCD Type 2 exists to solve (a fact must not
  drift when its dimension changes), solved by denormalizing the mapping
  into the fact row at load time instead of maintaining an effective-dated
  dimension table and a live join. No SCD machinery, because there's no
  live join left for a dimension change to leak through.

## Storage

### Horizontal Partitioner (ch. Data Storage)

- **Book:** pick a distribution key; store each partition value in its own
  physically isolated space so incremental jobs read only a slice.
- **Us:** the period `(fiscal_year, fiscal_period)` is the distribution
  key. It is the unit of load, replace, and backfill. In DuckDB this is
  logical, not physical, partitioning.

## Late data

### Late Data Detector (ch. Error Management)

- **Book:** define a time attribute, classify incoming records as late or
  on time, then apply a per-case strategy (often: ignore).
- **Us:** the FY2025 P02 rows. They are detected as outside current close
  scope, kept in `stg_gl`, and left out of the report until their period is
  in scope (Ticket 11).
- **Delta:** the book's case is streaming events past their window. Ours is
  a scope boundary on a batch period.

## Serving

### Readiness Marker (ch. Data Ingestion)

- **Book:** mark a dataset as ready so physically isolated downstream
  pipelines know when to start consuming. Often a flag file written after a
  successful run.
- **Us:** the signed `reports/period_YYYY-PP.md`. A period is not closed,
  and downstream should not trust its numbers, until a human accepts that
  report.

## Lineage

### Fine-Grained Tracker (ch. Data Lineage)

- **Book:** row or column-level detail about where each output came from.
- **Us:** `recon_mismatch`. Every difference between `stg_gl` and
  `fact_gl_line` carries one bucket (symptom) and one cause (reason), so
  any changed or missing row can be traced back to the rule that changed
  it.

---

## Considered and not used

- **Parallel Split:** a fan-out orchestration pattern (one parent task, N
  parallel children writing to different sinks). The P02/P03 backfill is
  just independent period loads, not a fan-out, so this label does not fit.
- **Dataset Tracker:** table-level lineage graphs across teams. Not what
  our run logs or `recon_mismatch` do. Fine-Grained Tracker is the right
  one for row-level cause tracking.
- **Manifest, CDC, Incremental Loader, streaming patterns:** not relevant
  to a bounded batch migration on a single engine.
