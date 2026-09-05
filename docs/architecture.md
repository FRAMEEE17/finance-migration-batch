# Architecture: drawing brief

Spec for the diagram (`docs/architecture.png`, draw.io): layered left to
right, one box per component, pattern names as labels. The pattern names
follow the vocabulary in Bartosz Konieczny's *Data Engineering Design
Patterns* (O'Reilly, 2025).

## Boxes and arrows (left → right)

```
┌─ SOURCE ─────────┐   ┌─ INGESTION ──────┐   ┌─ STORAGE (DuckDB) ─────────────┐
│ journal_entries  │──▶│ Full Loader      │──▶│ stg_gl  (raw, verbatim)        │
│ .parquet / .csv  │   │ (verbatim, no    │   │ 648,801 rows · never edited    │
│ 649k rows, 49 col│   │  transform)      │   └──────────┬─────────────────────┘
└──────────────────┘   └──────────────────┘              │
                                                         ▼
                              ┌─ QUALITY GATE / Audit-Write-Audit-Publish ────┐
                              │ blocking audits: unbalanced_document,         │
                              │ duplicate_source, map_fanout                  │
                              │ findings: local_amount_imbalance, unmapped_*  │
                              │     ├──▶ dq_violations   (Dead-Letter)        │
                              │     └──▶ recon_mismatch  (bucket + cause)     │
                              └──────────────────┬────────────────────────────┘
                                                 ▼
┌─ MAPPING ────────────┐   ┌─ PROCESSING (star schema) ──────────────────────┐
│ map_account.csv      │──▶│ fact_gl_line   (Data Overwrite per period,      │
│ human-approved       │   │                 Transactional Writer)           │
│ (Static Joiner)      │   │ dim_account    (505 accounts → 27 classes)      │
└──────────────────────┘   │ Horizontal Partitioner: (fiscal_year, period)   │
                           └──────────────────┬──────────────────────────────┘
                                              ▼
                           ┌─ RECONCILE (SQL) ───────────┐   ┌─ SERVING ─────────────┐
                           │ stg_gl vs fact_gl_line      │──▶│ reports/period_*.md   │
                           │ per period · per account    │   │ signed by finance     │
                           │ per document (FULL OUTER)   │   │ = "closed period"     │
                           └─────────────────────────────┘   └───────────────────────┘

bottom bars:
  Orchestration: Python scripts (sequential = Single Runner) ▸ future: Airflow
  Engine/Storage: DuckDB + Parquet                            ▸ future: Databricks / Azure SQL
  Late data:     FY2025 P02 held in stg (Late Data Detector)  ▸ future: Static Late Data Integrator
```

## Pattern legend (what to label where)

| Component | Pattern (book name) | Why here |
|---|---|---|
| CSV/parquet → `stg_gl` | **Full Loader** | bounded batch migration; no CDC/incremental needed |
| period replace, rerun-stable | **Data Overwrite** + **Transactional Writer** | idempotency: delete+insert whole partition in one txn |
| staging → publish gate | **Audit-Write-Audit-Publish** | audit before anything reaches `fact_gl_line` |
| rejected rows | **Dead-Letter** | unprocessable rows land in `dq_violations`, never vanish |
| duplicate grain | detector only, not Windowed Deduplicator | no version column exists, so block rather than auto-pick |
| `map_account` join | **Static Joiner** | enrichment from a small human-owned dataset |
| period partitions | **Horizontal Partitioner** | replace/backfill unit = one period |
| FY2025 P02 | **Late Data Detector** (now) → **Static Late Data Integrator** (later) | out-of-scope rows stay visible, no merge |
| P02/P03 backfill | **Parallel Split** | independent periods can load in parallel |
| run logs / run1-vs-run2 diff | **Dataset Tracker** (light) | row counts + totals per run |

## Scalability story (annotate as dashed "future" boxes)

Same layers, swappable engines. The SQL and the contracts do not change:
- DuckDB → Databricks / Azure Synapse (engine swap, star schema identical)
- Python scripts → Airflow DAG (same jobs, adds retry/backfill/SLA)
- local parquet → ADLS/S3 landing zone (same Full Loader semantics)

## Drawing checklist (done when…)

- [ ] every box above appears once, grouped into the 7 layers
- [ ] arrows follow the data, left→right, no cycles
- [ ] pattern names appear as small labels on their component
- [ ] the two bottom bars (orchestration / engine) with "future" swaps
- [ ] exported to `docs/architecture.png` and committed
