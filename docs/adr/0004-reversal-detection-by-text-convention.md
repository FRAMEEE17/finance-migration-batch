# Detect reversals from text convention, not a status column

**Status:** accepted

No `is_cancelled` or `reversal_of_doc_id` column exists. `predecessor_line_id`
is populated for only 13 of 40,386 rows in scope, too sparse to build a rule
on. The source does carry a real signal, just not a schema one:
`reference` starting `REV-<uuid>`, and `header_text` reading "Reversal of
`<document_id>`".

Decision: parse this convention to detect reversal documents, link each to
its original by the id embedded in `header_text`, and report the pair
together (both kept, net amount, linked ids). Do not infer cancellation from
document numbering, and do not delete either side of a detected pair.

Consequence: this rule breaks if the text convention changes upstream (e.g.
the "Reversal of" phrasing gets localized or reworded). If reversal counts
suddenly drop to zero after a data refresh, check the convention before
assuming there are no reversals that period.
