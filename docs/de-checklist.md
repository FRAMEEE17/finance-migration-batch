# DE checklist: what this project enforces

The DE checklist items this repo enforces, and where.

| Rule | Enforced by |
|---|---|
| E2E test on real data | whole dataset, not samples, `dataset/` |
| Version control everything | this git repo (code, mapping, docs, ADRs) |
| Script every repeated task | working rules in `docs/business-rules.md` |
| Rollback / recovery | replace-whole-period load, `docs/definitions.md` |
| Validate input before ingestion | Ticket 5 DQ checks, `docs/definitions.md` |
| Versioned schemas | schema + doc_type catalog in repo |
| Data contracts | `docs/definitions.md` + `map_account.csv` + `CONTEXT.md` |
| Never overwrite raw | `stg_gl` verbatim; source files never edited |
| Idempotent transformations | Ticket 4; row-count + doc-count + total match across reruns |
| Automated DQ (dup / referential) | `duplicate_source`, `unmapped_account`, `unbalanced_document`, `map_fanout` |
| Defend against source change | ADR-0004 (reversal convention fragility) |
| Edge-case test data | planted `is_fraud` / `is_anomaly` rows kept, never filtered (ADR-0003) |
| Log row counts / totals per run | loader run log, run-1 vs run-2 diff |
| Lineage | stg → fact → report, every dropped row carries bucket + cause |
| Alert on missing / dup / late | blocking DQ + late-arrival rule |
| Validate downstream after update | rerun + diff before sign-off |
| Document pipeline + owner | Ticket 12 runbook |

Deliberately **not** done in the first pass:
CI/CD, Airflow/dbt, env isolation, schema-evolution tooling, SLA monitoring,
freshness dashboards, cost monitoring, catalogs. Added only when the
reconciliation loop is signed off and a real need appears.
