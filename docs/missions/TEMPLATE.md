# Mission NN: <title>

- **Signal:** issue #NN, <source>
- **Confidence:** <high / medium / low>
- **Type:** <bug / request / risk / noise>
- **Decision:** <act / park / reject>, <one line why>

## Rules that apply

Quote the lines from `docs/business-rules.md`, `docs/definitions.md`, or an
ADR that constrain this mission.

## Exploration

`notebooks/NN-slug.ipynb`, if one exists for this mission. What it checked
before the mission's checks below were locked, and what it changed about
the plan (or "none" — didn't need one / nothing it found changed anything).

## Desired outcomes

- <what exists when this is done, artifact by artifact>

## Deterministic checks

Each computes a value and compares it, no judgement. These become
assertions in the script and entries in `src/checks.py`.

- [ ] <check> : <how>

## Non-deterministic checks

| Check | Who | How an agent verifies |
|---|---|---|
| <judgement call> | human / LLM | <the deterministic proxy an agent can run> |

## Non-goals

- <what this mission explicitly does not do>

## Human approvals

**Before build:**

- <approach decision to confirm>

**Before the output is used:**

- <sign-off gate>

## Retro

Filled after the mission closes. One rule this adds (ADR / a
`docs/definitions.md` line / a check in `src/checks.py`), or "none".
