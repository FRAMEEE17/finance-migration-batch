# Notebooks

Exploration and presentation material, one optional notebook per mission:
`NN-slug.ipynb`, matching `docs/missions/NN-slug.md`.

Not the pipeline. Queries run through `duckdb` against `warehouse.duckdb`,
the same SQL the production script in `src/` will run, so a chart or a
schema preview here is looking at the real thing, not a pandas copy of it.
SQL stays the reconcile engine (`docs/business-rules.md`); a notebook
can't be held accountable by `src/checks.py` on every rerun, so the actual
logic always ends up as a `.py` script regardless of what got prototyped
here first.

Run locally:

```bash
pip install jupyterlab duckdb
jupyter lab
```

No container, no dashboard service. This project is not one
(`CLAUDE.md`).
