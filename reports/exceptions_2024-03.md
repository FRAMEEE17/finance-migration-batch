# Exception appendix: 2024-03

Company 1000, period 03. Material items only.

## 1. local_amount broadcast documents

Same document set and total as the working paper's Known Issue section
(materiality > 0.01): **36** documents, **340,498,930.1**. Root cause: `source='AB'` (mission 13).

| document_id | source | document_type | lines | net local_amount |
|---|---|---|---|---|
| ce738e9e-bc01-8a8e-2e7e-c5b3af381500 | AB | SA | 56 | 219,719,072.88 |
| 4626830c-92c7-850c-25bc-9dbd3ac580cb | AB | DR | 42 | 40,296,979.16 |
| 62aa5557-f3c5-85cf-1d9c-5eeaf7a8e078 | AB | KR | 45 | 37,795,774.17 |
| 4e598d88-ec64-8ec4-0cf9-c56a131998cd | AB | KR | 77 | 12,687,938.25 |
| f3720f27-b080-8ded-137e-af3ec5200d2c | AB | SA | 59 | 9,558,761.49 |
| 5c3eeb97-77e4-85ec-1363-6f062561f5ab | AB | DR | 43 | 5,198,047.65 |
| 409ad70b-3b66-8d13-2c50-0b32c8fb93ee | AB | HR | 56 | 2,274,137.32 |
| 9f29e7d5-a6f7-8130-355a-52890557f963 | AB | DR | 71 | 2,007,207.24 |
| f34893dd-fb40-8fd0-0f5b-809f157d778e | AB | SA | 76 | 1,868,474.10 |
| 39696813-77e1-8b1e-2472-1ca043627415 | AB | HR | 34 | 1,465,914.56 |
| ff92d589-213e-855d-177a-b8a0a269ee4a | AB | HR | 51 | 983,370.71 |
| 4fe383a8-2f4c-8b15-0016-5ed4b37299ca | AB | DR | 47 | 964,807.20 |
| 74c2dec4-ae62-8e90-0099-06ca562f7658 | AB | AA | 69 | 737,364.48 |
| 59175f36-bc71-8317-1bfe-c815a3ff9d7e | AB | KR | 59 | 495,185.60 |
| 67b03375-fd1f-85b9-39e4-97ad56ea6c32 | AB | DR | 39 | 452,569.57 |
| aebe150c-d4cf-8d87-04d5-76682bcba7b5 | AB | KR | 57 | 410,213.11 |
| 1a53347f-aaf1-8f80-2223-c7331e75defe | AB | DR | 59 | 389,463.90 |
| 46544117-0535-836b-1ac4-5dd93b883b9d | AB | SA | 46 | 386,574.76 |
| b766d5d9-111a-8bbb-3cae-372ecdca8929 | AB | DR | 38 | 316,251.00 |
| 560faf17-62d9-8fb8-2e33-b20a7b3ffa24 | AB | KR | 51 | 279,638.59 |
| db4c6840-7b78-89d5-312c-a586476d97e5 | AB | KR | 54 | 274,383.20 |
| 10ed1baf-610c-806f-371e-4c7f106b1377 | AB | DR | 44 | 240,076.80 |
| 13d3e442-7d1a-888e-211e-c8e5174543a3 | AB | HR | 61 | 234,818.23 |
| 1a9f7d15-3094-85a0-0e3f-3d4a0530390e | AB | DR | 59 | 212,042.85 |
| b8c52c32-e309-89af-068f-005fe09b646d | AB | DR | 75 | 197,912.49 |
| ae52732a-fb91-80e8-0451-54a1e7f4ef2a | AB | SA | 44 | 193,200.00 |
| 97924a6a-36cf-8453-3038-85aa0b286294 | AB | KR | 58 | 191,114.29 |
| 0f28f78b-0105-85c2-3d0e-5f3a6c6d62eb | AB | DR | 71 | 185,090.43 |
| 9d169905-4144-89e8-195d-47713f7259df | AB | SA | 66 | 184,656.64 |
| 1342b365-be7d-8d48-121b-89945229a43f | AB | DR | 49 | 97,225.58 |
| e6ce67ee-988b-8d4f-11c3-7ddfcb63f1ea | AB | DR | 32 | 73,100.59 |
| baf3f9bc-6681-89a0-22c4-d869f784a486 | AB | DR | 51 | 36,288.42 |
| 4364b67c-f6ff-8729-240f-33c939b3aa72 | AB | AA | 42 | 31,492.50 |
| 440b2d3c-45b6-80d2-0346-b1c5a7de5dc0 | AB | SA | 57 | 30,336.67 |
| 1f69923f-2456-8f10-2859-29c358c4df6d | AB | DR | 47 | 25,320.60 |
| ce4eeff0-b561-8513-0460-13ec5e5f0977 | AB | HR | 73 | 4,125.10 |

## 2. catch_all accounts (ADR-0005)

Migration parking codes, not real accounts. Listed for visibility, not
as a defect - `map_account.csv status='catch_all'`.

| gl_account | lines this period | net local_amount |
|---|---|---|
| 199999 | 61 | 3,756,863.38 |
| 999999 | 30 | 180,805.19 |

## 3. Designed zero-local clearing pairs (ADR-0007)

`local_amount` is 0 on every row of these accounts by design, not a
defect - do not read activity here as a new local_amount problem.

| gl_account | pair_id | lines this period | sum debit | sum credit |
|---|---|---|---|---|
| 115020 | 115020_205020 | 3 | 412,160.19 | 0.00 |
| 115021 | 115021_205021 | 3 | 75,227.85 | 0.00 |
| 115030 | 115030_205030 | 1 | 10,899.44 | 0.00 |
| 205020 | 115020_205020 | 2 | 0.00 | 118,449.27 |
| 205021 | 115021_205021 | 2 | 0.00 | 64,796.52 |
| 205030 | 115030_205030 | 3 | 0.00 | 265,315.21 |

## 4. Text-only reversal mismatches (mission 07)

The reversal text convention matched (`REV-...` reference), but the
amounts don't correspond to the claimed original. Flagged, never
filtered - most carry an `is_fraud`/`is_anomaly` flag.

| original_document_id | reversal_document_id | fraud/anomaly flagged |
|---|---|---|
| 03d12e2c-9d2c-444c-b35c-87f9572b32e8 | 51947869-cf7f-0500-e119-d1bc057873a4 | yes |
| 142b7bbd-bc5c-4dbd-babe-150f738a6a5c | 466e2df8-ee0f-0cf1-e8fb-434a21d92b10 | yes |
| 166b1e08-4e75-40b3-be8f-1208fb70172e | 442e484d-1c26-01ff-ecca-444da9235662 | yes |
| 1a8a94ff-2ac8-4256-9b8e-91ebac5a2e65 | 48cfc2ba-789b-031a-c9cb-c7aefe096f29 | yes |
| 1e8547a2-820c-4bab-91c2-57973cf1f47e | 4cc011e7-d05f-0ae7-c387-01d26ea2b532 | yes |
| 1e8bd306-1d32-468f-966f-006b596f0222 | 4cce8543-4f61-07c3-c42a-562e0b3c436e | yes |
| 2b421c79-eb12-4747-8016-6339967bcb38 | 79074a3c-b941-060b-d253-357cc4288a74 | yes |
| 3522a3b7-2899-4758-848b-daeb38cea0f9 | 6767f5f2-7aca-0614-d6ce-8cae6a9de1b5 | yes |
| 36d50612-0a5b-487a-8221-ad5850860596 | 64905057-5808-0936-d064-fb1d02d544da | yes |
| 49dd2efd-782c-4ddc-b575-2275b116c8f1 | 1b9878b8-2a7f-0c90-e730-7430e34589bd | yes |
| 4c2b4edc-63e2-48a0-8d22-6a11bff662fd | 1e6e1899-31b1-09ec-df67-3c54eda523b1 | yes |
| 5b4d36e0-9a51-44a3-9314-00aa6c43594e | 090860a5-c802-05ef-c151-56ef3e101802 | yes |
| 6b39712d-3931-4c80-a987-2b33cf5decf5 | 397c2768-6b62-0dcc-fbc2-7d769d0eadb9 | yes |
| 720559e6-8ec8-4fc5-8754-82b72c1808f0 | 20400fa3-dc9b-0e89-d511-d4f27e4b49bc | yes |
| 799dcca0-fbcc-4c1f-8592-fad56c842360 | 2bd89ae5-a99f-0d53-d7d7-ac903ed7622c | yes |
| 7b178335-0c7b-4531-ae32-ca15fb82b3d7 | 2952d570-5e28-047d-fc77-9c50a9d1f29b | yes |
| 8fa1e65e-5dac-4cab-a21f-a22f29fc40b0 | dde4b01b-0fff-0de7-f05a-f46a7baf01fc | yes |
| 9f8d5c91-e729-44f1-bfb4-79fadea6317e | cdc80ad4-b57a-05bd-edf1-2fbf8cf57032 | yes |
| a0cff1b2-a0e5-45da-ba19-64d8f7a000fb | f28aa7f7-f2b6-0496-e85c-329da5f341b7 | yes |
| a2013815-1f95-4615-97ad-d3a7c6944c7c | f0446e50-4dc6-0759-c5e8-85e294c70d30 | yes |
| a3126159-83d9-44fe-9b85-58890f9e0e78 | f157371c-d18a-05b2-c9c0-0ecc5dcd4f34 | yes |
| a37e3516-8751-4608-b3fd-bb55ec08de46 | f13b6353-d502-0744-e1b8-ed10be5b9f0a | yes |
| ac648602-44ab-46d2-96ef-c57c4397a31a | fe21d047-16f8-079e-c4aa-933911c4e256 | yes |
| ae1422fc-80ec-4f65-afdd-578f75a2c22d | fc5174b9-d2bf-0e29-fd98-01ca27f18361 | yes |
| bc1ad4d0-81c9-4ba7-97cb-b463425145ad | ee5f8295-d39a-0aeb-c58e-e226100204e1 | yes |
| c58602bc-8ee0-4508-b318-3db084b21814 | 97c354f9-dcb3-0444-e15d-6bf5d6e15958 | yes |
| ceafdbfd-ffeb-4882-9c8e-be9022138eb1 | 9cea8db8-adb8-09ce-cecb-e8d57040cffd | yes |
| d49d7957-1b3a-4bbd-b53c-09fbe1f17d24 | 86d82f12-4969-0af1-e779-5fbeb3a23c68 | yes |
| dcb77d33-1c92-4056-9709-a38f6504ead7 | 8ef22b76-4ec1-011a-c54c-f5ca3757ab9b | yes |
| e4f9c07d-fab5-418b-aa68-a092612d2c8f | b6bc9638-a8e6-00c7-f82d-f6d7337e6dc3 | yes |
| e5bba5d1-13e4-4fd4-bd46-e671c2ca025f | b7fef394-41b7-0e98-ef03-b03490994313 | yes |
| f55545cd-196d-449f-8d8f-1c71f444e6dd | a7101388-4b3e-05d3-dfca-4a34a617a791 | yes |
| f78272b8-9e6d-4bd0-9a74-cd20bf0d78b1 | a5c724fd-cc3e-0a9c-c831-9b65ed5e39fd | yes |
| f8929951-ceae-4bca-bf27-522ce9fc5ef6 | aad7cf14-9cfd-0a86-ed62-0469bbaf1fba | yes |

