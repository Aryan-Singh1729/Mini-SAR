# Phase 2A — Dataset Understanding and Data Dictionary

## Scope and source

This document describes the user-provided, relationship-preserving 50% reduced dataset located at:

```text
C:\Users\hp\Desktop\Hackathons\Barclays SAR\files (1)\reduced_50pct
```

It is an input dataset, not application source code. No SQLite schema, database, import code, or synthetic records were created in Phase 2A.

## Dataset inventory

| File | Rows | Columns | Logical primary key | Purpose |
| --- | ---: | ---: | --- | --- |
| `customers.csv` | 26 | 20 | `customer_id` | Customer identity, KYC, declared income, and risk context. |
| `accounts.csv` | 27 | 9 | `account_id` | Accounts owned by customers. |
| `transactions.csv` | 2,350 | 17 | `transaction_id` | Transactional evidence for AML signals. |
| `aml_alerts_history.csv` | 6 | 9 | `alert_id` | Historical alerts and previous analyst outcomes. |
| `watchlists.csv` | 21 | 16 | `watchlist_id` | Screening records for customers and counterparties. |

All five files are CSV files. CSV has no native types, so every field initially arrives as text; Phase 2B will assign SQLite storage types and Phase 2C will validate/convert safely.

## Relationships

```text
customers.customer_id  (1) ──< accounts.customer_id
customers.customer_id  (1) ──< aml_alerts_history.customer_id
accounts.account_id    (1) ──< transactions.account_id

watchlists.entity_name / aliases
    └── screened against customers.full_name and transactions.counterparty_name
```

Validation result for the reduced dataset:

| Relationship check | Invalid references |
| --- | ---: |
| `accounts.customer_id` → `customers.customer_id` | 0 |
| `aml_alerts_history.customer_id` → `customers.customer_id` | 0 |
| `transactions.account_id` → `accounts.account_id` | 0 |

Every declared primary-key column is unique in its source file. The watchlist is intentionally not linked through a foreign key: it is a screening reference list, not a customer/account child table.

## `customers.csv` — customer/KYC source

| Column | Source form | Meaning and AML use |
| --- | --- | --- |
| `customer_id` | text ID | Unique customer key; parent key for accounts and alert history. |
| `full_name` | text | Customer legal name; used in watchlist screening. |
| `date_of_birth` | ISO date text | Identity disambiguation for similar names. |
| `nationality` | text | Geographic/customer-risk context. |
| `country_of_residence` | text | Customer location-risk context. |
| `customer_type` | categorical text | Individual or business context for expected activity. All retained rows are `INDIVIDUAL`. |
| `occupation` | text | Helps assess whether activity is plausible. |
| `employer_name` | text | Additional income/source-of-funds context. |
| `annual_income_declared_gbp` | decimal text | Declared annual income; input to deterministic income-mismatch calculations. |
| `source_of_funds_declared` | text | Expected origin of customer funds. |
| `onboarding_date` | ISO date text | Relationship age. |
| `kyc_status` | categorical text | KYC control status. Retained values are `VERIFIED` and `EXPIRED`. |
| `kyc_last_reviewed` | ISO date text | KYC recency. |
| `kyc_document_type` | text | Type of identity document used in KYC. |
| `kyc_document_expiry` | ISO date text | Expired document/KYC-control context. |
| `pep_flag` | Boolean-like text | Politically exposed person indicator. All retained values are `False`. |
| `sanctions_flag` | Boolean-like text | Existing customer-profile sanctions indicator. All retained values are `False`. |
| `risk_rating` | categorical text | Internal risk rating. Retained values are `LOW` and `MEDIUM`. |
| `address` | text | Detailed address for identity context; sensitive personal data. |
| `address_country` | text | Address geography; consistency/geographic-risk context. |

No values are missing in `customers.csv`. All declared-income values parse as numbers; the retained range is £22,000 to £95,000.

## `accounts.csv` — account source

| Column | Source form | Meaning and AML use |
| --- | --- | --- |
| `account_id` | text ID | Unique account key; parent key for transactions. |
| `customer_id` | text ID | Foreign key to the account owner. |
| `account_type` | categorical text | Product context. Retained values are `CURRENT` and `SAVINGS`. |
| `currency` | categorical text | Account currency. All retained values are `GBP`. |
| `account_status` | categorical text | Active/closed/dormant control context. All retained values are `ACTIVE`. |
| `opening_date` | `DD-MM-YYYY` date text | Account age. |
| `last_activity_date` | `DD-MM-YYYY` date text | Activity recency and dormancy calculation. |
| `average_monthly_balance_gbp` | decimal text | Baseline account value for unusual-activity comparison. |
| `iban` | text | International bank-account identifier; sensitive account data. |

No values are missing. All 27 account dates use `DD-MM-YYYY`, unlike the ISO-style dates in the other files. The importer must parse this format explicitly and store a normalized ISO date. `average_monthly_balance_gbp` parses as numeric and ranges from £1,240.50 to £9,807.28.

## `transactions.csv` — transactional evidence source

| Column | Source form | Meaning and AML use |
| --- | --- | --- |
| `transaction_id` | text ID | Unique evidence reference for an investigation. |
| `account_id` | text ID | Foreign key to the account used. Customer identity is derived through `accounts.customer_id`. |
| `transaction_datetime` | ISO datetime text | Timing for alert windows, structuring, and rapid-movement analysis. |
| `transaction_type` | categorical text | Payment/deposit category. |
| `direction` | categorical text | `CREDIT` or `DEBIT`; required for inflow/outflow aggregation. |
| `amount_gbp` | decimal text | Standardized GBP amount used in deterministic AML calculations. |
| `original_amount` | decimal text | Amount in original transaction currency. |
| `original_currency` | text | Original currency context. |
| `counterparty_name` | text | Counterparty-screening input. |
| `counterparty_account_id` | text | Known counterparty-account reference, when applicable. |
| `counterparty_bank_bic` | text | Counterparty bank identifier. |
| `counterparty_country` | text | Geographic-risk context. |
| `counterparty_is_high_risk_jurisdiction` | Boolean-like text | Deterministic high-risk-jurisdiction signal. |
| `payment_reference` | nullable text | Payment narrative/reference. |
| `channel` | categorical text | Transaction channel. |
| `is_international` | Boolean-like text | Cross-border indicator. |
| `transaction_status` | categorical text | Completion state; only completed activity should count in movement calculations. |

There are 6 missing `payment_reference` values; all other transaction fields are populated. Both amount columns parse as numeric. `amount_gbp` ranges from £40.23 to £75,000.00. Transaction dates span 2024-01-01 08:00:00 to 2024-11-28 18:00:00.

Retained categories are:

- `direction`: 283 `CREDIT`, 2,067 `DEBIT`;
- `transaction_type`: `BACS`, `CARD_PAYMENT`, `FASTER_PAYMENT`, and `SWIFT`;
- `channel`: `MOBILE_APP` and `ONLINE_BANKING`;
- `transaction_status`: all `COMPLETED`;
- `is_international`: 4 `True`, 2,346 `False`;
- `counterparty_is_high_risk_jurisdiction`: 3 `True`, 2,347 `False`.

## `aml_alerts_history.csv` — historical-alert source

| Column | Source form | Meaning and AML use |
| --- | --- | --- |
| `alert_id` | text ID | Unique historical-alert key. |
| `customer_id` | text ID | Foreign key to the investigated customer. |
| `alert_date` | ISO date text | Historical alert chronology. |
| `alert_type` | categorical text | Monitoring scenario that originally triggered. |
| `rules_triggered` | text | Rule label(s) associated with the historical alert. |
| `disposition` | categorical text | Previous investigation outcome. |
| `sar_filed` | Boolean-like text | Whether a SAR was filed previously. |
| `sar_reference` | nullable text | SAR/case reference, where one exists. |
| `analyst_notes` | text | Earlier analyst explanation and false-positive/recurrence context. |

All 6 retained alerts have `rules_triggered = RULE-04`, `disposition = FALSE_POSITIVE`, and `sar_filed = False`; therefore every `sar_reference` is blank. Alert dates span 2022-03-27 to 2023-10-16, which is earlier than the retained transaction period in 2024.

## `watchlists.csv` — screening-reference source

| Column | Source form | Meaning and AML use |
| --- | --- | --- |
| `watchlist_id` | text ID | Unique screening-record key. |
| `entity_name` | text | Primary name for exact-match screening. |
| `aliases` | text | Alternate names/spellings for alias screening. |
| `entity_type` | categorical text | Person, organisation, or other entity context. |
| `watchlist_type` | categorical text | List category, such as sanctions or PEP. |
| `source` | text | Originating authority/list provenance. |
| `listed_date` | ISO date text | Date the entity was listed. |
| `country_of_incorporation` | text | Entity registration-country context. |
| `country_of_operation` | text | Entity operating-country context. |
| `risk_score` | integer-like text | Severity/priority score. |
| `is_absolute_prohibition` | Boolean-like text | Whether a relationship is prohibited. |
| `status` | categorical text | Whether the record is active or under review. |
| `last_reviewed_date` | ISO date text | Screening-record recency. |
| `review_due_date` | ISO date text | Next review-control date. |
| `related_entity_id` | nullable text ID | Optional connection to another watchlist entity. |
| `notes` | text | Additional screening context. |

`related_entity_id` is blank in 18 of 21 rows; this is valid for standalone entities but must remain nullable. `risk_score` parses as numeric and ranges from 55 to 100. Retained list types are `SANCTIONS`, `PEP`, `ADVERSE_MEDIA`, and `INTERNAL_BLACKLIST`; statuses are `ACTIVE` and `UNDER_REVIEW`.

## AML rule fitness

| Rule | Available fields | Dataset support | Important limitation |
| --- | --- | --- | --- |
| `RULE-01` Structuring/smurfing | `transaction_datetime`, `direction`, `amount_gbp`, `transaction_type`, `account_id` | Supports repeated-credit analysis under a configurable threshold. | There is no cash transaction type in the retained data, so the project must call this a general repeated-credit/structuring pre-signal rather than claim cash structuring. |
| `RULE-02` Rapid movement | `transaction_datetime`, `direction`, `amount_gbp`, `account_id`, `counterparty_name` | Supports credit-to-debit timing, total debit/credit, and retention-ratio calculations. | All retained transactions are completed; there is no pending/reversed behavior to demonstrate status filtering. |
| `RULE-03` Income mismatch | `annual_income_declared_gbp`, `occupation`, `source_of_funds_declared`, `amount_gbp`, `direction` | Supports comparing credit volume with declared income and customer context. | Declared income is self-reported; it is an indicator, not proof of illicit activity. |
| `RULE-04` Watchlist/sanctions proximity | `full_name`, `counterparty_name`, `entity_name`, `aliases`, `watchlist_type`, `risk_score`, `status` | Supports exact, alias, and cautious fuzzy matching. | The reduced data has no exact/alias customer-name match and one exact/pipe-alias counterparty match. A fuzzy match must be labeled as proximity, not a confirmed sanctions hit. |

## Data-quality findings and design implications

1. **Referential integrity is good.** Primary keys are unique and all three declared foreign-key relationships are valid. Phase 2C can enforce these as SQLite foreign keys.
2. **Date formats are inconsistent.** Account dates are `DD-MM-YYYY`; most other dates are ISO-like. The import pipeline must use per-column date parsers and store normalized ISO values.
3. **The reduced alert-history subset is not outcome-balanced.** It has six false positives and zero filed SARs. The original full alert-history file contains one true positive and two pending outcomes, but those rows are not in the reduced copy. The application must not claim that it has a representative labeled training/evaluation set.
4. **Alert dates and transaction dates do not overlap.** Retained alerts are from 2022–2023 while retained transactions are in 2024. `aml_alerts_history.csv` should be treated as historical context, not as a ready-to-run alert queue with a transaction observation window.
5. **No source alert-window fields exist.** There is no `observation_start` or `observation_end` column. A future `/investigate` request must receive a user-selected/derived window, or a documented deterministic window policy must be added. It must not be fabricated silently.
6. **The account source has an average balance, not a current balance.** Phase 2B should map `average_monthly_balance_gbp` accurately; it must not label it as a current `balance`.
7. **Transaction records do not carry `customer_id`.** This is not a data error: customer identity is deterministically derived through the account relationship.
8. **Some nullable fields are expected.** Missing payment references, SAR references, and related watchlist entity IDs must remain nullable rather than being replaced by made-up values.
9. **Sensitive fields require care.** Full names, birth dates, addresses, IBANs, and analyst notes should not be exposed unnecessarily in SSE events or logs. Tool outputs should return only the evidence required for the active investigation.

## Phase 2B decisions to make next

Phase 2B will design the physical SQLite schema from this dictionary. It will map source names faithfully—for example `full_name` rather than a fabricated `name`, `account_status` rather than a generic `status`, and `average_monthly_balance_gbp` rather than a misleading current balance.

Application-owned tables—`audit_runs`, `audit_events`, and `human_reviews`—will be designed separately because they do not come from the source CSVs. No CSV will be forced to contain those fields.
