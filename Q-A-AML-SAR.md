# Q/A AML SAR Investigator

## Q1) Why did you use SQLite instead of PostgreSQL/MySQL or MongoDB?

We used SQLite because our AML SAR Investigator needed structured relational storage, but the project was a hackathon-style prototype where speed and simplicity mattered. The data naturally fit relational tables such as customers, accounts, transactions, alert history and watchlists, so SQL queries were the right fit.

SQLite gave us joins, filtering and aggregation without setting up a separate database server, credentials or deployment configuration. For our dataset size of roughly a few thousand transactions, SQLite was fast enough and easy to package with the project.

MongoDB was not the best choice because the data had strong relationships, and AML investigations often require structured joins across customer, account and transaction records.

PostgreSQL or MySQL would be better for a production banking system because they support concurrency, scaling, access control and stronger operational features. But for our prototype, using them would have added unnecessary setup complexity without improving the core investigation logic.

So SQLite was a practical engineering trade-off: simple for demo and development, relational enough for AML evidence retrieval, and replaceable with PostgreSQL in production.

## Q2) What data did you use in this project, and how did you create them?

I used five linked CSV files: `customers.csv`, `accounts.csv`, `transactions.csv`, `aml_alerts_history.csv`, and `watchlists.csv`. Together they model the core AML investigation journey: an alert identifies a customer; the customer owns accounts; accounts contain transactions; transaction counterparties and customer names are screened against watchlists; and previous alerts provide historical analyst context.

### How I created the dataset

I manually assembled the dataset for the hackathon from multiple structured source documents and organised the information into consistent CSV files. I kept common identifiers across the files so that customers, accounts, transactions, and alert history could be joined during an investigation. I then included transaction patterns and watchlist information that support AML review scenarios such as structuring, rapid movement of funds, income mismatch, and sanctions/watchlist proximity.

The important engineering step was not only creating the files, but maintaining the relationships:

```text
accounts.customer_id          -> customers.customer_id
transactions.account_id       -> accounts.account_id
aml_alerts_history.customer_id -> customers.customer_id
```

For the mini version, I created a separate 50% reduced copy while preserving these links; the original files remain unchanged.

### `customers.csv`

- `customer_id`: unique customer key.
- `full_name`: identity and watchlist-screening name.
- `date_of_birth`: helps distinguish people with similar names.
- `nationality`, `country_of_residence`, `address_country`: geographic-risk context.
- `customer_type`: identifies an individual or business.
- `occupation`, `employer_name`: describe expected customer activity.
- `annual_income_declared_gbp`: supports income-mismatch checks.
- `source_of_funds_declared`: records the expected funding source.
- `onboarding_date`: shows relationship age.
- `kyc_status`, `kyc_last_reviewed`, `kyc_document_type`, `kyc_document_expiry`: show KYC completeness and recency.
- `pep_flag`: identifies politically exposed persons.
- `sanctions_flag`: existing sanctions-related indicator.
- `risk_rating`: internal customer risk level.
- `address`: detailed address for identity context.

### `accounts.csv`

- `account_id`: unique account key.
- `customer_id`: links the account to its owner.
- `account_type`: describes the product.
- `currency`: account currency.
- `account_status`: shows whether the account is active, closed, or dormant.
- `opening_date`: shows account age.
- `last_activity_date`: supports dormancy and recency checks.
- `average_monthly_balance_gbp`: normal-balance baseline.
- `iban`: international bank account identifier.

### `transactions.csv`

- `transaction_id`: unique transaction-evidence key.
- `account_id`: links the transaction to an account.
- `transaction_datetime`: provides timing for alert windows and rapid-movement checks.
- `transaction_type`: identifies the payment/deposit type.
- `direction`: shows whether funds entered or left the account.
- `amount_gbp`: standardised amount used in calculations.
- `original_amount`, `original_currency`: preserve the original payment value.
- `counterparty_name`: screened against the watchlist.
- `counterparty_account_id`: identifies a known counterparty account.
- `counterparty_bank_bic`: identifies the counterparty bank.
- `counterparty_country`, `counterparty_is_high_risk_jurisdiction`: geographic-risk context.
- `payment_reference`: payment narrative.
- `channel`: identifies how the transaction occurred.
- `is_international`: flags cross-border activity.
- `transaction_status`: distinguishes completed, pending, or reversed activity.

### `aml_alerts_history.csv`

- `alert_id`: unique historical-alert key.
- `customer_id`: links the alert to the customer.
- `alert_date`: provides chronology.
- `alert_type`: records the monitoring scenario.
- `rules_triggered`: records the AML rules that fired.
- `disposition`: earlier investigation outcome.
- `sar_filed`: indicates whether a SAR was filed.
- `sar_reference`: SAR case reference when available.
- `analyst_notes`: previous analyst reasoning, including legitimate-activity or false-positive context.

### `watchlists.csv`

- `watchlist_id`: unique watchlist-record key.
- `entity_name`: primary screening name.
- `aliases`: alternate spellings or names.
- `entity_type`: distinguishes a person, company, or other entity.
- `watchlist_type`: describes the list category.
- `source`: identifies the originating list.
- `listed_date`: records when the entity was listed.
- `country_of_incorporation`, `country_of_operation`: geographic context.
- `risk_score`: indicates severity.
- `is_absolute_prohibition`: identifies a prohibited relationship.
- `status`: shows whether the record is active.
- `last_reviewed_date`, `review_due_date`: support data governance.
- `related_entity_id`: connects related listed entities.
- `notes`: additional screening context.

### Controlled retrieval and responsible AI

This is structured-data retrieval rather than vector RAG. The investigation agent will not query these CSV files or SQLite directly. Controlled Python tools will retrieve only the relevant customer, account, transaction, alert-history, and watchlist evidence; Python will calculate deterministic risk signals; and the LLM will interpret those bounded tool outputs into an auditable verdict.
