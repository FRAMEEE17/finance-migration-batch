# Balance validation uses debit/credit; close totals use local_amount

**Status:** accepted

`debit_amount − credit_amount` nets to zero for all but 1 of 10,939 documents
in the FY2024 P01–P03 / company `1000` scope. `local_amount` fails to net to
zero for 86 of those same documents, from independent rounding introduced
by currency conversion rather than a document-level imbalance. Treating these as one
check would either falsely block 86 otherwise-good documents, or mask real
imbalances by using a noisier column.

Decision: `unbalanced_document` (publish-blocking) is decided on
`debit_amount − credit_amount`. Close totals reported to finance use
`local_amount`, since that's the home-currency figure finance actually wants.
The 86-document gap is surfaced as its own finding, `local_amount_imbalance`,
not folded into `unbalanced_document`.

Consequence: any new check involving "balance" must say which of the two it
means. The terms are not interchangeable in this project.
