# Missions

One mission per ticket, written before any code. A mission turns a GitHub
issue into a structured object: the rules that constrain it, the outcomes,
the checks (deterministic first), and what a human signs off.

Flow per ticket:

1. Issue is the signal. Write `NN-slug.md` from `TEMPLATE.md`.
2. Human approves the approach (the "before build" list).
3. Build. Deterministic checks become assertions in the script and entries
   in `src/checks.py`.
4. Validator pass (`/scrutinize` or Codex) on anything with judgement.
5. Human signs off the output.
6. Retro: the mission gains at most one durable rule (an ADR, a line in
   `docs/definitions.md`, or a check). Not "fix everything from the trace".

`src/checks.py` is the running regression eval. Every check stays green
across every ticket.
