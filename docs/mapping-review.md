# Mapping review: draft for #3

Draft, not approved. See `docs/missions/01-chart-of-accounts-mapping.md`.

## 1. Target groups (27 account_class values)

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

## 2. Unmapped (no account_class, needs your ruling)

| gl_account | description | lines | net local |
|---|---|---|---|
| `115020` | None | 4 | 0 |
| `115021` | None | 10 | 0 |
| `115030` | None | 3 | 0 |
| `205020` | None | 8 | 0 |
| `205021` | None | 7 | 0 |
| `205030` | None | 9 | 0 |

## 3. Deprecated proposal (suspense / clearing, needs your ruling)

| gl_account | description | lines | net local |
|---|---|---|---|
| `9000` | General Suspense | 150 | -2,645,631 |
| `9100` | Payroll Clearing | 300 | -5,089,762 |
| `9300` | IC Elimination Suspense | 185 | 373,860 |
| `199000` | Suspense Clearing | 30 | 435,492 |
| `199300` | Intercompany Clearing | 218 | 6,690,828 |
| `199999` | Acc. Dep. — Vehicles | 174 | 5,751,571 |
| `999999` | Accounts Payable 12 | 78 | 878,756 |

## 4. Classes that split across financial_statement_category (each account is internally consistent; accounts within the same class disagree with each other, needs your ruling)

| class | name | category | accounts | lines | net local |
|---|---|---|---|---|---|
| `A.A` | Cash & Cash Equivalents | asset | 17 | 1,472 | -6,188,671 |
| `A.A` | Cash & Cash Equivalents | suspense | 1 | 123 | -80,883 |
| `A.X` | Suspense & Clearing (Asset side) | asset | 3 | 422 | 12,877,891 |
| `A.X` | Suspense & Clearing (Asset side) | suspense | 4 | 713 | -6,482,776 |
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
