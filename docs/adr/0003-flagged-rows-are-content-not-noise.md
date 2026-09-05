# is_fraud / is_anomaly rows flow through the pipeline; never filtered

**Status:** accepted

The source dataset plants `is_fraud` (766 rows) and `is_anomaly` (1,623 rows)
in scope as deliberate defects, with `fraud_type` / `anomaly_type` columns
describing each one. The obvious-looking move, `WHERE is_fraud = false`
before loading, would make totals look clean while hiding exactly the
content this project exists to surface.

Decision: these rows are reconciliation content. They load like any other
row; if they cause a difference between `stg_gl` and `fact_gl_line`, they
appear in the mismatch report with cause drawn from their `*_type` column.
`is_post_close` is handled differently (excluded from in-period totals, own
report bucket) because it is not a defect. It is a timing fact, not a
question of trust.

Consequence: a "clean" totals run does not mean fraud/anomaly rows are
absent. It means they were priced into the report with a named cause. Do not
"fix" a future data-quality complaint by adding a filter on these flags.
