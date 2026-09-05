# finance-migration-batch

ERP/SAP-like Finance Migration + Reconciliation. Move legacy GL into a new
warehouse so finance can close a period and explain every difference.

## Docs

- `docs/business-rules.md`: working rules + domain rules
- `CONTEXT.md`: domain glossary
- `docs/requirements.md`: goal, personas, scope, definition of done
- `docs/definitions.md`: every term pinned (grain, buckets, causes, guards)
- `docs/architecture.md`: drawing brief for `docs/architecture.png` (design-pattern labelled)
- `docs/de-checklist.md`: which of the 33 DE rules this repo enforces
- `docs/adr/`: architecture decision records

## Work

12 tickets tracked as GitHub issues (`gh issue list`). Dependency order is
enforced with native blocked-by edges; start any issue whose blockers are
all closed.

