# Exception appendix: 2024-02

Company 1000, period 02. Material items only.

## 1. local_amount broadcast documents

Same document set and total as the working paper's Known Issue section
(materiality > 0.01): **27** documents, **104,111,412.6**. Root cause: `source='AB'` (mission 13).

| document_id | source | document_type | lines | net local_amount |
|---|---|---|---|---|
| fed5dfee-1356-8c59-158b-68354df5bb92 | AB | HR | 41 | 63,123,588.45 |
| 24984c80-7a65-8385-083d-62a0fc5dc9d1 | AB | KR | 50 | 9,591,636.00 |
| 355cfcba-46ed-8553-2e09-a1a4591d5fe1 | AB | HR | 79 | 6,620,841.15 |
| fc9ea8e3-9340-8599-0064-c5a26673a4a9 | AB | HR | 80 | 4,812,390.96 |
| cf8f533f-b3fa-88cc-2797-87e23c19dc03 | AB | KR | 73 | 2,611,746.36 |
| 49abd9dd-bbf2-8c35-0784-47fbaaec5144 | AB | KR | 50 | 2,154,701.76 |
| 4b9f0d77-2173-8b0c-1f19-dfb129bb4bd3 | AB | KR | 40 | 2,019,985.76 |
| f9362a83-b349-8228-1b71-f2ff7e772939 | AB | HR | 33 | 1,548,359.01 |
| 52b8fd30-5c78-84ae-1a1e-c4c69eb26ebb | AB | KR | 60 | 1,536,395.84 |
| 92caa420-f270-8507-146f-0975c090040d | AB | SA | 78 | 1,331,384.32 |
| 3809fa68-b8e0-8618-17a3-96e99bf1687f | AB | HR | 80 | 1,297,427.82 |
| a71ea559-ecce-8a0b-13d1-e773de039c10 | AB | KR | 68 | 1,174,514.88 |
| 973e3273-2ea0-8d28-0bdd-069b2a29f6f9 | AB | DR | 60 | 935,260.44 |
| 0d1dc8ce-410e-849e-044c-85e4f21c18b7 | AB | DR | 42 | 913,057.60 |
| a1712e39-b47d-860f-2199-5c69a7d22e51 | AB | SA | 50 | 804,765.02 |
| e30fb1a9-7d66-8086-16b8-ad58ae900e38 | AB | DR | 74 | 725,995.44 |
| 66fe59f1-2d31-8219-2eb0-dd840dc79078 | AB | DR | 71 | 564,877.67 |
| 31f7aef6-5b7a-8dcd-0181-881eb63ac072 | AB | DR | 62 | 401,791.20 |
| 18a1c264-923d-8851-3f9b-eaca86dda7b3 | AB | KR | 63 | 379,114.39 |
| 8b612b74-c48d-84f9-06cd-24bf16de821d | AB | KR | 46 | 287,475.76 |
| 6ef8aecf-0d69-82b7-162a-91897a25954e | AB | DR | 63 | 247,564.84 |
| 2e1d0409-f767-859b-2d7d-205eaa4fa6f8 | AB | KR | 49 | 244,152.78 |
| 8af9a201-ccc7-81f6-3240-bbc59f13ca85 | AB | KR | 70 | 233,865.60 |
| accae2f4-b965-8567-3ec3-b4e394609bd5 | AB | SA | 79 | 231,319.55 |
| b37286b1-6f0f-8090-0efa-d51643c7de42 | AB | SA | 48 | 152,896.05 |
| 252ed189-9a3f-8ca5-1ef8-fff89de371cb | AB | HR | 59 | 127,024.50 |
| acda0812-ef3d-833b-3d10-4a05f5529358 | AB | KR | 69 | 39,279.42 |

## 2. catch_all accounts (ADR-0005)

Migration parking codes, not real accounts. Listed for visibility, not
as a defect - `map_account.csv status='catch_all'`.

| gl_account | lines this period | net local_amount |
|---|---|---|
| 199999 | 64 | 372,679.98 |
| 999999 | 27 | 837,179.86 |

## 3. Designed zero-local clearing pairs (ADR-0007)

`local_amount` is 0 on every row of these accounts by design, not a
defect - do not read activity here as a new local_amount problem.

| gl_account | pair_id | lines this period | sum debit | sum credit |
|---|---|---|---|---|
| 115020 | 115020_205020 | 1 | 158,462.73 | 0.00 |
| 115021 | 115021_205021 | 2 | 620,295.94 | 0.00 |
| 205020 | 115020_205020 | 4 | 0.00 | 1,224,215.77 |
| 205021 | 115021_205021 | 2 | 0.00 | 1,668,359.24 |
| 205030 | 115030_205030 | 3 | 0.00 | 397,226.20 |

## 4. Text-only reversal mismatches (mission 07)

The reversal text convention matched (`REV-...` reference), but the
amounts don't correspond to the claimed original. Flagged, never
filtered - most carry an `is_fraud`/`is_anomaly` flag.

| original_document_id | reversal_document_id | fraud/anomaly flagged |
|---|---|---|
| 1ca6d542-5620-4e58-b564-180e35f2aed5 | 4ee38307-0473-0f14-e721-4e4b67a1ef99 | yes |
| 34676546-af77-40db-992f-6aa9a82644c9 | 66223303-fd24-0197-cb6a-3cecfa750585 | yes |
| 432426d7-ad14-4128-b3bc-9e020f08017b | 11617092-ff47-0064-e1f9-c8475d5b4037 | yes |
| 5997a53c-1b64-413f-8a25-10497415d017 | 0bd2f379-4937-0073-d860-460c2646915b | yes |
| 8a45eee9-7e40-43d9-9a81-e649888e18d6 | d800b8ac-2c13-0295-c8c4-b00cdadd599a | yes |
| a1223a1b-57f2-4c5e-ba55-eea49a204c69 | f3676c5e-05a1-0d12-e810-b8e1c8730d25 | no |
| a6cec732-0448-4625-8642-6200c9cb5814 | f48b9177-561b-0769-d407-34459b981958 | yes |
| b7891cc5-ebad-4917-825c-a240db2d5168 | e5cc4a80-b9fe-085b-d019-f405897e1024 | yes |
| b92bfa9c-a1ce-4273-a966-29e2f8402546 | eb6eacd9-f39d-033f-fb23-7fa7aa13640a | yes |
| cb897221-5978-48a3-9e98-0acbffb7b459 | 99cc2464-0b2b-09ef-ccdd-5c8eade4f515 | yes |
| d6cb0f3e-2035-4253-8893-6170a2d46de6 | 848e597b-7266-031f-dad6-3735f0872caa | yes |
| d810a327-26b3-40a2-916f-ffa66318f117 | 8a55f562-74e0-01ee-c32a-a9e3314bb05b | yes |
| e385ef2f-f554-4031-b990-00d9f1cb1b46 | b1c0b96a-a707-017d-ebd5-569ca3985a0a | yes |
| eb3136fb-a432-4457-a93b-8e3e2937c9a7 | b97460be-f661-051b-fb7e-d87b7b6488eb | yes |
| f065557e-092b-4f16-aaf6-557d46460d3d | a220033b-5b78-0e5a-f8b3-033814154c71 | yes |
| f21bfd1e-2c9a-4a13-9952-29bccd2735b4 | a05eab5b-7ec9-0b5f-cb17-7ff99f7474f8 | yes |
| f8548c85-4794-4981-b1a6-f37090a02ee7 | aa11dac0-15c7-08cd-e3e3-a535c2f36fab | yes |
| f97ed82f-ec0b-473a-9c28-dd6d03b2e034 | ab3b8e6a-be58-0676-ce6d-8b2851e1a178 | yes |
| fa2c5398-156a-46ae-a1c8-3824c9b21b69 | a86905dd-4739-07e2-f38d-6e619be15a25 | yes |

