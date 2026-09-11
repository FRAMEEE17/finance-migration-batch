# Exception appendix: 2024-01

Company 1000, period 01. Material items only.

## 1. local_amount broadcast documents

Same document set and total as the working paper's Known Issue section
(materiality > 0.01): **20** documents, **97,144,587.1**. Root cause: `source='AB'` for 19 of these (mission 13); the rest is unrelated sub-cent rounding, kept here only because it shares the same materiality-filtered total the working paper quotes.

| document_id | source | document_type | lines | net local_amount |
|---|---|---|---|---|
| 0a121d1e-7334-81f7-2608-9bb9a6e55fab | AB | KR | 37 | 41,646,671.85 |
| ff37e2f8-570f-80bb-046a-739063b0c380 | AB | KR | 64 | 16,496,633.76 |
| baf325f1-de3b-8184-2f67-00817c86f1d7 | AB | SA | 79 | 11,304,573.28 |
| 51ad9376-2306-8f69-0bee-722d35801425 | AB | KR | 62 | 7,629,389.71 |
| bd3fc32d-5d1d-8922-3373-87b930724279 | AB | SA | 55 | 5,932,511.00 |
| dfc53943-7e93-843c-2664-683f0e4c28c9 | AB | DR | 71 | 4,844,919.41 |
| 20a0d33e-f594-8582-0eee-9da0e065bc85 | AB | DR | 33 | 2,044,140.00 |
| dbbe683e-696e-8d08-2d71-67834f4954b0 | AB | KR | 53 | 1,356,524.52 |
| 2262522b-2e0f-87a8-2304-a1881e4a55aa | AB | SA | 33 | 1,305,988.15 |
| cbf097de-1be0-8976-2aab-d40b3316783a | AB | HR | 60 | 1,130,060.98 |
| c5dd30e6-02e8-8a81-28d1-a4fe713550f2 | AB | SA | 44 | 1,128,214.63 |
| fdc7e1c3-e307-87cb-2d81-3dbb83595714 | AB | SA | 56 | 1,104,546.24 |
| 7774e114-9b83-8201-3ccf-6de980be4e44 | AB | KR | 53 | 578,374.45 |
| 3bcd28ba-edfb-8f01-2adf-a32def290a6b | AB | HR | 81 | 241,980.16 |
| 3af302ba-77e8-82e2-11db-57e303349c86 | AB | DR | 57 | 181,149.10 |
| 5ff2f0cc-65bf-8c01-21e9-028ba7d9f02e | AB | KR | 69 | 162,708.84 |
| 953dabc5-e2dd-8b6a-3bbb-4379598d7565 | AB | KR | 44 | 21,712.37 |
| 353be192-5f97-8937-1088-a6596c687c7a | AB | KR | 52 | 18,262.92 |
| 9371824c-b750-826e-2db9-714505100536 | AB | KR | 75 | 16,225.71 |
| 65267292-3137-4d6d-8054-d7eebdddbf55 | RV | SA | 18 | 0.02 |

## 2. catch_all accounts (ADR-0005)

Migration parking codes, not real accounts. Listed for visibility, not
as a defect - `map_account.csv status='catch_all'`.

| gl_account | lines this period | net local_amount |
|---|---|---|
| 199999 | 49 | 1,622,027.22 |
| 999999 | 21 | -139,228.84 |

## 3. Designed zero-local clearing pairs (ADR-0007)

`local_amount` is 0 on every row of these accounts by design, not a
defect - do not read activity here as a new local_amount problem.

| gl_account | pair_id | lines this period | sum debit | sum credit |
|---|---|---|---|---|
| 115021 | 115021_205021 | 5 | 1,070,150.04 | 0.00 |
| 115030 | 115030_205030 | 2 | 454,414.02 | 0.00 |
| 205020 | 115020_205020 | 2 | 0.00 | 280,190.19 |
| 205021 | 115021_205021 | 3 | 0.00 | 53,284.06 |
| 205030 | 115030_205030 | 3 | 0.00 | 318,046.87 |

## 4. Text-only reversal mismatches (mission 07)

The reversal text convention matched (`REV-...` reference), but the
amounts don't correspond to the claimed original. Flagged, never
filtered - most carry an `is_fraud`/`is_anomaly` flag.

| original_document_id | reversal_document_id | fraud/anomaly flagged |
|---|---|---|
| 0397a7c9-d214-4b8e-962f-67e3ee8e2c70 | 51d2f18c-8047-0ac2-c46a-31a6bcdd6d3c | yes |
| 13b7b2af-ab14-42bf-97d1-5af26680805a | 41f2e4ea-f947-03f3-c594-0cb734d3c116 | yes |
| 15ee4b45-e754-4bed-a894-cfd813b50a47 | 47ab1d00-b507-0aa1-fad1-999d41e64b0b | yes |
| 161efd4c-933f-4a81-a2dd-3e71057773f2 | 445bab09-c16c-0bcd-f098-6834572432be | yes |
| 1b240ae0-c853-41c9-8ca3-9f8174d0a0df | 49615ca5-9a00-0085-dee6-c9c42683e193 | yes |
| 2350ce91-c6a0-4ccd-a714-f4fb26d7fe7c | 711598d4-94f3-0d81-f551-a2be7484bf30 | yes |
| 2366a110-341d-408f-886b-a30a1d007d32 | 7123f755-664e-01c3-da2e-f54f4f533c7e | yes |
| 26e2fab1-ca24-4986-95ff-c516619bb8b1 | 74a7acf4-9877-08ca-c7ba-935333c8f9fd | yes |
| 2871a4e7-5169-4039-b2d9-5626b353f1b6 | 7a34f2a2-033a-0175-e09c-0063e100b0fa | yes |
| 3f411466-c312-4ed4-8778-cbcec80fb2a1 | 6d044223-9141-0f98-d53d-9d8b9a5cf3ed | yes |
| 3f76ed67-94a6-4f72-a807-dc78b4d75d11 | 6d33bb22-c6f5-0e3e-fa42-8a3de6841c5d | yes |
| 48b07205-ac6d-4e6e-b7c3-78c4a203030e | 1af52440-fe3e-0f22-e586-2e81f0504242 | yes |
| 4f049759-612f-4884-8f50-51f846890d84 | 1d41c11c-337c-09c8-dd15-07bd14da4cc8 | yes |
| 61e3b463-7c35-498a-8184-8d5f3be6973d | 33a6e226-2e66-08c6-d3c1-db1a69b5d671 | yes |
| 67d0c630-3b68-4583-9781-afdeaea17184 | 35959075-693b-04cf-c5c4-f99bfcf230c8 | no |
| 74916ef5-f9d1-4ddf-af20-3772e93002e4 | 26d438b0-ab82-0c93-fd65-6137bb6343a8 | yes |
| 75ea9951-cac3-4373-84c8-531b6cef844a | 27afcf14-9890-023f-d68d-055e3ebcc506 | yes |
| 8ec5036e-f6b3-4347-8b86-3140bc6742a3 | dc80552b-a4e0-020b-d9c3-6705ee3403ef | yes |
| 987305e8-41a1-40d0-a0e0-5afdaf8ac1a1 | ca3653ad-13f2-019c-f2a5-0cb8fdd980ed | yes |
| ad5ca81f-8b2b-443e-ab10-5fb1ae98e68e | ff19fe5a-d978-0572-f955-09f4fccba7c2 | yes |
| bcaad1ca-4a7b-49b7-b86d-41174b29977d | eeef878f-1828-08fb-ea28-1752197ad631 | yes |
| bd3e6131-bc8c-41f1-bb14-c36599ee63c0 | ef7b3774-eedf-00bd-e951-9520cbbd228c | yes |
| bd63d867-26af-4254-a079-e49994a1ee7e | ef268e22-74fc-0318-f23c-b2dcc6f2af32 | yes |
| d32a0155-a1ca-45d8-9271-3c11c8e4c563 | 816f5710-f399-0494-c034-6a549ab7842f | yes |
| ded68a5e-7501-4ecd-a71e-92c0e183611e | 8c93dc1b-2752-0f81-f55b-c485b3d02052 | yes |
| f118d17d-a24b-43e3-8c9c-5504238d651e | a35d8738-f018-02af-ded9-034171de2452 | yes |
| f3e6dbd6-0e0c-4f45-8feb-5b26b2c70c71 | a1a38d93-5c5f-0e09-ddae-0d63e0944d3d | yes |
| f4b2098a-6a23-4f52-8f64-ad60fd77b5bd | a6f75fcf-3870-0e1e-dd21-fb25af24f4f1 | yes |
| f4e1f80a-0e1f-4e2e-bbad-82b40b9b334a | a6a4ae4f-5c4c-0f62-e9e8-d4f159c87206 | yes |
| fb31ccd5-914d-412e-827b-79071cd1104d | a9749a90-c31e-0062-d03e-2f424e825101 | yes |
| fd27ceb3-bdbc-4c5c-acfb-3a9d2adedb0e | af6298f6-efef-0d10-febe-6cd8788d9a42 | yes |
| fff8defc-10e3-4329-95e0-890d957dd1f9 | adbd88b9-42b0-0265-c7a5-df48c72e90b5 | yes |

