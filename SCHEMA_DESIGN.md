# Phase 2B — SQLite Schema Design

## Goal

This schema is designed from [DATA_DICTIONARY.md](DATA_DICTIONARY.md), not from a generic AML template. The five source tables retain the supplied CSV names and column meanings. Three additional tables (`audit_runs`, `audit_events`, and `human_reviews`) belong to the application and will be populated only when investigations run.

`app/database.py` contains the executable schema. Running it creates an empty `data/aml.db`; it does not import CSV rows. Importing is deliberately deferred to Phase 2C.

## SQLite choices

- SQLite has flexible typing, so IDs, names, dates, and JSON are stored as `TEXT`.
- Imported dates will be normalized to ISO text (`YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`) for lexical sorting and predictable filtering. The source account dates are converted from `DD-MM-YYYY` by the future importer.
- GBP amounts use `NUMERIC` with non-negative checks. This is readable for a mini project; a production money model would generally use integer minor units or a fixed decimal implementation.
- Source `True`/`False` values become integer `1`/`0`, with `CHECK (... IN (0, 1))` constraints.
- `PRAGMA foreign_keys = ON` is executed for every connection because SQLite does not enforce foreign keys unless each connection enables it.

## Relationship design

```text
customers (1) ──< accounts (1) ──< transactions
     │
     └──────────< aml_alerts_history

audit_runs ──< audit_events
     │
     └──────────< human_reviews

watchlists is a reference table used for name screening; it has no FK to a customer or transaction.
```

`audit_runs.customer_id` has a foreign key to `customers`. Its `alert_id` is intentionally not a foreign key: the source file contains **historical** alerts only, while a future investigation may receive a current alert payload or a derived alert ID. This avoids falsely claiming every new investigation alert exists in `aml_alerts_history`.

## Source-derived tables

### `customers`

| Column | SQLite type/constraint | Why it is stored |
| --- | --- | --- |
| `customer_id` | `TEXT PRIMARY KEY` | Stable customer identity and relationship parent. |
| `full_name` | `TEXT NOT NULL` | Controlled name screening. |
| `date_of_birth` | `TEXT NOT NULL` | Name-match disambiguation. |
| `nationality` | `TEXT NOT NULL` | Geographic/customer-risk context. |
| `country_of_residence` | `TEXT NOT NULL` | Geographic-risk context. |
| `customer_type` | `TEXT NOT NULL` | Expected-activity context. |
| `occupation` | `TEXT NOT NULL` | Plausibility of activity. |
| `employer_name` | `TEXT NOT NULL` | Income/source context. |
| `annual_income_declared_gbp` | `NUMERIC NOT NULL`, non-negative | Deterministic income-mismatch baseline. |
| `source_of_funds_declared` | `TEXT NOT NULL` | Expected funding-source evidence. |
| `onboarding_date` | `TEXT NOT NULL` | Customer relationship age. |
| `kyc_status` | `TEXT NOT NULL` | KYC-control status. |
| `kyc_last_reviewed` | `TEXT NOT NULL` | KYC recency. |
| `kyc_document_type` | `TEXT NOT NULL` | Identity-document context. |
| `kyc_document_expiry` | `TEXT NOT NULL` | Expired-document control context. |
| `pep_flag` | `INTEGER` constrained to `0/1` | PEP-risk indicator. |
| `sanctions_flag` | `INTEGER` constrained to `0/1` | Existing sanctions-risk indicator. |
| `risk_rating` | `TEXT NOT NULL` | Internal risk classification. |
| `address` | `TEXT NOT NULL` | Sensitive identity context. |
| `address_country` | `TEXT NOT NULL` | Address geography/consistency context. |

### `accounts`

| Column | SQLite type/constraint | Why it is stored |
| --- | --- | --- |
| `account_id` | `TEXT PRIMARY KEY` | Stable account identity. |
| `customer_id` | `TEXT NOT NULL`, FK to `customers` | Owner relationship. |
| `account_type` | `TEXT NOT NULL` | Product/expected-activity context. |
| `currency` | `TEXT NOT NULL` | Account-currency context. |
| `account_status` | `TEXT NOT NULL` | Active/dormant/closed account context. |
| `opening_date` | `TEXT NOT NULL`, normalized ISO on import | Account age. |
| `last_activity_date` | `TEXT NOT NULL`, normalized ISO on import | Days-since-activity calculation. |
| `average_monthly_balance_gbp` | `NUMERIC NOT NULL`, non-negative | Normal-balance comparison; not mislabeled as current balance. |
| `iban` | `TEXT NOT NULL` | Sensitive account identifier. |

### `transactions`

| Column | SQLite type/constraint | Why it is stored |
| --- | --- | --- |
| `transaction_id` | `TEXT PRIMARY KEY` | Evidence and audit reference. |
| `account_id` | `TEXT NOT NULL`, FK to `accounts` | Account relationship; customer is derived through the account. |
| `transaction_datetime` | `TEXT NOT NULL`, normalized ISO | Time-window and ordering analysis. |
| `transaction_type` | `TEXT NOT NULL` | Payment-pattern context. |
| `direction` | `TEXT NOT NULL`, `CREDIT`/`DEBIT` check | Credit/debit aggregation. |
| `amount_gbp` | `NUMERIC NOT NULL`, non-negative | Standardized AML amount. |
| `original_amount` | `NUMERIC NOT NULL`, non-negative | Original transaction amount. |
| `original_currency` | `TEXT NOT NULL` | Original currency context. |
| `counterparty_name` | `TEXT NOT NULL` | Watchlist screening input. |
| `counterparty_account_id` | `TEXT NOT NULL` | Counterparty-repeat analysis. |
| `counterparty_bank_bic` | `TEXT NOT NULL` | Counterparty-bank context. |
| `counterparty_country` | `TEXT NOT NULL` | Geographic-risk context. |
| `counterparty_is_high_risk_jurisdiction` | `INTEGER` constrained to `0/1` | Deterministic geography signal. |
| `payment_reference` | nullable `TEXT` | Narrative evidence; source has six blanks. |
| `channel` | `TEXT NOT NULL` | Channel-pattern analysis. |
| `is_international` | `INTEGER` constrained to `0/1` | Cross-border signal. |
| `transaction_status` | `TEXT NOT NULL` | Completed/pending/reversed filtering. |

### `aml_alerts_history`

| Column | SQLite type/constraint | Why it is stored |
| --- | --- | --- |
| `alert_id` | `TEXT PRIMARY KEY` | Historical-alert identity. |
| `customer_id` | `TEXT NOT NULL`, FK to `customers` | Investigated customer. |
| `alert_date` | `TEXT NOT NULL`, normalized ISO | Historical chronology. |
| `alert_type` | `TEXT NOT NULL` | Monitoring scenario context. |
| `rules_triggered` | `TEXT NOT NULL` | Historic AML rule labels. |
| `disposition` | `TEXT NOT NULL` | Historic investigator outcome. |
| `sar_filed` | `INTEGER` constrained to `0/1` | Prior SAR outcome. |
| `sar_reference` | nullable `TEXT` | SAR reference; source is blank when no SAR was filed. |
| `analyst_notes` | `TEXT NOT NULL` | Prior false-positive or escalation evidence. |

### `watchlists`

| Column | SQLite type/constraint | Why it is stored |
| --- | --- | --- |
| `watchlist_id` | `TEXT PRIMARY KEY` | Watchlist-record identity. |
| `entity_name` | `TEXT NOT NULL` | Exact-match screening target. |
| `aliases` | `TEXT NOT NULL` | Alias-match screening target. |
| `entity_type` | `TEXT NOT NULL` | Person/organisation match context. |
| `watchlist_type` | `TEXT NOT NULL` | Sanctions/PEP/list-category context. |
| `source` | `TEXT NOT NULL` | List provenance. |
| `listed_date` | `TEXT NOT NULL`, normalized ISO | Listing chronology. |
| `country_of_incorporation` | `TEXT NOT NULL` | Registration-country context. |
| `country_of_operation` | `TEXT NOT NULL` | Operating-country context. |
| `risk_score` | `INTEGER NOT NULL`, `0–100` check | Severity prioritization. |
| `is_absolute_prohibition` | `INTEGER` constrained to `0/1` | Prohibition indicator. |
| `status` | `TEXT NOT NULL` | Active/under-review status. |
| `last_reviewed_date` | `TEXT NOT NULL`, normalized ISO | Data-recency control. |
| `review_due_date` | `TEXT NOT NULL`, normalized ISO | Next review control. |
| `related_entity_id` | nullable `TEXT` | Optional network link; source has many blanks. |
| `notes` | `TEXT NOT NULL` | Additional screening context. |

## Application-owned audit tables

### `audit_runs`

| Column | SQLite type/constraint | Why it is stored |
| --- | --- | --- |
| `investigation_id` | `TEXT PRIMARY KEY` | UUID-style correlation ID for one investigation. |
| `alert_id` | `TEXT NOT NULL` | Submitted/derived alert identifier; not forced to be historical. |
| `customer_id` | `TEXT NOT NULL`, FK to `customers` | Customer under investigation. |
| `started_at` | `TEXT NOT NULL` | Investigation start time. |
| `completed_at` | nullable `TEXT` | Completion/failure time. |
| `status` | `RUNNING`, `COMPLETED`, or `FAILED` | Investigation lifecycle. |
| `final_verdict` | nullable TP/FP value | Validated final agent recommendation. |
| `confidence` | nullable numeric `0–1` | Verdict confidence. |
| `llm_provider` | nullable `TEXT` | Model-provider audit metadata. |
| `model_name` | nullable `TEXT` | Exact model audit metadata. |

### `audit_events`

| Column | SQLite type/constraint | Why it is stored |
| --- | --- | --- |
| `event_id` | `TEXT PRIMARY KEY` | Unique event identity. |
| `investigation_id` | `TEXT NOT NULL`, FK to `audit_runs` | Event-to-run relationship. |
| `sequence_number` | positive integer, unique per run | Durable chronological order. |
| `event_type` | `TEXT NOT NULL` | Event category, such as `TOOL_CALLED` or `TOOL_RESULT`. |
| `timestamp` | `TEXT NOT NULL` | Event time. |
| `payload_json` | `TEXT NOT NULL` | Safe structured event payload. |

### `human_reviews`

| Column | SQLite type/constraint | Why it is stored |
| --- | --- | --- |
| `review_id` | `TEXT PRIMARY KEY` | Unique review identity. |
| `investigation_id` | `TEXT NOT NULL`, FK to `audit_runs` | Reviewed investigation. |
| `reviewer` | `TEXT NOT NULL` | Human reviewer name/identifier. |
| `decision` | `approved` or `rejected` | Explicit human decision. |
| `notes` | `TEXT NOT NULL` | Human justification/context. |
| `reviewed_at` | `TEXT NOT NULL` | Review timestamp. |

## Indexes

Indexes are created for the queries the later tools and audit endpoints will perform most often:

- `accounts(customer_id)` for account-summary retrieval;
- `transactions(account_id, transaction_datetime)` for bounded time-window history;
- `aml_alerts_history(customer_id, alert_date)` for prior-alert retrieval;
- `audit_runs(started_at)` for run listing;
- `audit_events(investigation_id, sequence_number)` for ordered audit retrieval;
- `human_reviews(investigation_id)` for review lookup.

## What is intentionally deferred to Phase 2C

- CSV/Excel discovery and file-path configuration;
- `True`/`False` to `1`/`0` conversion;
- `DD-MM-YYYY` account-date normalization;
- parameterized inserts and transaction handling;
- row-count, null, duplicate, date, and foreign-key validation;
- actual data insertion.
