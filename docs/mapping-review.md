# Mapping review: draft for #3

Draft, not approved. See `docs/missions/01-chart-of-accounts-mapping.md` and `docs/adr/0005-account-status-catch-all.md`.

## 1. Target groups (27 account_class values)

Ordinary rollup accounts: `target_account` = `account_class`.

| class | name | gl accounts | lines | net local |
|---|---|---|---|---|
| `L.B` | Accrued Liabilities | 31 | 2,451 | -11,447,794 |
| `A.A` | Cash & Cash Equivalents | 18 | 1,595 | -6,269,554 |
| `E.A` | Contributed Capital | 19 | 1,419 | -10,963,871 |
| `X.A` | Cost of Goods Sold | 32 | 3,023 | 111,860,501 |
| `X.D` | Depreciation & Amortisation | 13 | 950 | -11,361,840 |
| `A.G` | Intangible Assets | 4 | 320 | 5,593,462 |
| `X.E` | Interest Expense | 5 | 421 | 62,319,413 |
| `A.C` | Inventory | 15 | 1,723 | 13,109,986 |
| `L.E` | Long-term Debt | 13 | 801 | -8,151,742 |
| `R.A` | Operating Revenue | 60 | 4,447 | 196,604,717 |
| `E.C` | Other Comprehensive Income | 16 | 1,270 | 48,151,523 |
| `X.G` | Other Expenses | 9 | 937 | -2,154,169 |
| `R.B` | Other Income | 28 | 2,079 | -31,902,353 |
| `A.H` | Other Long-term Assets | 5 | 420 | 853,943 |
| `L.F` | Other Long-term Liabilities | 7 | 862 | 16,970,486 |
| `A.D` | Prepaid Expenses & Other Current Assets | 8 | 366 | 77,308,054 |
| `A.F` | Property, Plant & Equipment | 53 | 4,256 | 17,576,300 |
| `E.B` | Retained Earnings | 17 | 1,458 | 5,644,299 |
| `X.B` | Selling, General & Administrative | 68 | 4,851 | 60,850,772 |
| `L.C` | Short-term Debt | 11 | 641 | 4,087,128 |
| `A.X` | Suspense & Clearing (Asset side) | 7 | 1,135 | 6,395,114 |
| `X.F` | Tax Expense | 6 | 485 | -47,607,903 |
| `L.D` | Tax Liabilities | 12 | 1,187 | 39,143,449 |
| `L.A` | Trade Payables | 20 | 1,334 | -11,141,247 |
| `A.B` | Trade Receivables | 21 | 1,766 | 14,020,224 |
| `E.D` | Treasury Stock | 1 | 148 | 2,266,032 |
| `None` | None | 6 | 41 | 0 |

## 2. Clearing accounts (`status=mapped`, `account_role=clearing`, `target_account` = own code)
Real, single-purpose clearing/suspense accounts. All confirmed `source_usage=live` across the full dataset (postings continue past the current scope, in every company) so each keeps its own code as target rather than being marked `deprecated`.

| gl_account | description | lines | net local |
|---|---|---|---|
| `9000` | General Suspense | 150 | -2,645,631 |
| `9100` | Payroll Clearing | 300 | -5,089,762 |
| `9300` | IC Elimination Suspense | 185 | 373,860 |
| `199000` | Suspense Clearing | 30 | 435,492 |
| `199300` | Intercompany Clearing | 218 | 6,690,828 |

## 3. Clearing pairs (`status=unmapped`, `account_role=clearing_pair`, `dq_flag=local_amount_zero_but_dr_cr_nonzero`)
Debit-only / credit-only pairs. `local_amount` is 0 on every row for all six despite real debit/credit activity below. Do not read this set as immaterial from `local_amount` alone. Filed against issue #5. Stay `unmapped` until a human names the real pair target; never map one side without the other.

| gl_account | sum debit | sum credit | lines |
|---|---|---|---|
| `115020` | 570,623 | 0 | 4 |
| `115021` | 1,765,674 | 0 | 10 |
| `115030` | 465,313 | 0 | 3 |
| `205020` | 0 | 1,622,855 | 8 |
| `205021` | 0 | 1,786,440 | 7 |
| `205030` | 0 | 980,588 | 9 |

## 4. Catch-all accounts (`status=catch_all`, ADR-0005)
Migration parking codes, not real accounts: many unrelated `account_description` values on the same code, active across all 4 companies and 13 periods in the full source (see ADR-0005). Each keeps its own code as `target_account` and reports on its own line, never merged with the other even though both fall under `account_class` `A.X`. Within the current scope they land in different `financial_statement_category` values and folding them together would misclassify one of them. `fs_category_flag` is forced true for both, and both are excluded from section 5's `A.X` vote.

| gl_account | financial_statement_category (in scope) | lines (in scope) | net local (in scope) | distinct descriptions (in scope) |
|---|---|---|---|---|
| `199999` | asset | 174 | 5,751,571 | 18 |
| `999999` | suspense | 78 | 878,756 | 12 |

In-scope figures only. The full-dataset picture is far larger: `199999` carries 180,162,775 net local across 4 companies and 13 periods; `999999` carries 1,736,047. Neither total belongs to the current scope's close.


## 5. Classes that split across financial_statement_category (each account is internally consistent; accounts within the same class disagree with each other, needs your ruling; catch-all accounts excluded, see section 4)

| class | name | category | accounts | lines | net local |
|---|---|---|---|---|---|
| `A.A` | Cash & Cash Equivalents | asset | 17 | 1,472 | -6,188,671 |
| `A.A` | Cash & Cash Equivalents | suspense | 1 | 123 | -80,883 |
| `A.X` | Suspense & Clearing (Asset side) | asset | 2 | 248 | 7,126,320 |
| `A.X` | Suspense & Clearing (Asset side) | suspense | 3 | 635 | -7,361,532 |
| `L.B` | Accrued Liabilities | asset | 1 | 53 | 185,875 |
| `L.B` | Accrued Liabilities | liability | 30 | 2,398 | -11,633,668 |
| `X.A` | Cost of Goods Sold | cogs | 31 | 2,849 | 65,221,047 |
| `X.A` | Cost of Goods Sold | operating_expense | 1 | 174 | 46,639,454 |
| `X.B` | Selling, General & Administrative | cogs | 56 | 4,116 | 45,860,582 |
| `X.B` | Selling, General & Administrative | operating_expense | 11 | 688 | 13,858,585 |
| `X.B` | Selling, General & Administrative | other_income_expense | 1 | 47 | 1,131,606 |
| `X.D` | Depreciation & Amortisation | cogs | 10 | 807 | -17,508,599 |
| `X.D` | Depreciation & Amortisation | operating_expense | 2 | 61 | 1,208,326 |
| `X.D` | Depreciation & Amortisation | other_income_expense | 1 | 82 | 4,938,433 |
| `X.F` | Tax Expense | cogs | 5 | 417 | -42,951,853 |
| `X.F` | Tax Expense | tax | 1 | 68 | -4,656,050 |
| `X.G` | Other Expenses | cogs | 5 | 459 | -15,527,913 |
| `X.G` | Other Expenses | other_income_expense | 4 | 478 | 13,373,745 |
