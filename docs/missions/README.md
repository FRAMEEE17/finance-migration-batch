# Missions

One mission per ticket, written before any code. A mission turns a GitHub
issue into a structured object: the rules that constrain it, the outcomes,
the checks (deterministic first), and what a human signs off.

Flow per ticket:

1. Issue is the signal. Write `NN-slug.md` from `TEMPLATE.md`.
2. **Exploration (optional).** Before locking the mission's checks, poke at
   the data in `notebooks/NN-slug.ipynb`: schema/distribution previews,
   quick plots, sanity queries. Uses the `duckdb` Python API against
   `warehouse.duckdb`, the same queries the production script will run.
   This is where a first-pass assumption gets caught before it's written
   into a script and a check both agree on the wrong answer (see mission
   01's retro: two of three rulings changed once the full dataset was
   checked instead of the scoped one). Whatever the notebook finds feeds
   the mission's Deterministic / Non-deterministic checks below. The
   notebook is exploration and presentation material, not the pipeline:
   SQL run through `duckdb`, not pandas, is still the reconcile engine
   (`docs/business-rules.md`), and the actual logic still gets written as
   a `.py` script in `src/`, because that's what `src/checks.py` can hold
   accountable on every rerun. A notebook isn't.
3. Human approves the approach (the "before build" list).
4. Build. Deterministic checks become assertions in the script and entries
   in `src/checks.py`.
5. Validator pass (`/scrutinize` or Codex) on anything with judgement.
6. Human signs off the output.
7. Retro: the mission gains at most one durable rule (an ADR, a line in
   `docs/definitions.md`, or a check). Not "fix everything from the trace".

`src/checks.py` is the running regression eval. Every check stays green
across every ticket.
