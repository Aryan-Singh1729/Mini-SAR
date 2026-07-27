# Mini AML SAR Investigator — Learning Notes by Phase

This document is the single theory guide for the phases completed so far. It explains not only *what* was created, but *why* it exists, how data flows through it, how to test it, and how to explain the decisions in an interview.

Completed phases:

1. Phase 1 — Project setup and boundaries
2. Phase 2A — Dataset understanding and data dictionary
3. Phase 2B — SQLite schema design from the actual dataset
4. Phase 2C — CSV import pipeline and validation
5. Phase 3 — Database helpers and controlled AML tools
6. Phase 4 — Audit logger and evidence package
7. Phase 5 — LangChain and LangGraph investigation agent
8. Phase 5 setup correction — Groq configuration and VS Code imports
9. Phase 5 checkpoint — End-to-end Groq agent classification test

The project intentionally has no generated AML customers, transactions, alerts, or watchlist entries. It is built around the CSV data supplied by the project owner.

---

## Phase 1 — Project setup and boundaries

### Goal

Create a clean, understandable project structure before writing database, API, agent, or AML-rule code. Phase 1 establishes where each concern will live, but it does not perform an investigation.

### What was created

```text
mini-sar/
├── app/
│   ├── agent/
│   ├── audit/
│   ├── static/
│   └── tools/
├── audit/
│   ├── evidence_logs/
│   └── sar_drafts/
├── data/
├── .env.example
├── .gitignore
├── implementation.md
├── requirements.txt
└── Q-A-AML-SAR.md
```

### Why the folders are separated

| Location | Future responsibility | Why it is separate |
| --- | --- | --- |
| `app/` | Python application source | Keeps code separate from data and generated investigation artifacts. |
| `app/agent/` | LangGraph state, prompts, LLM configuration, graph loop | The agent decides which controlled evidence tool to call; it must not contain direct SQL access. |
| `app/tools/` | Customer, account, transaction, alert-history, and watchlist tools | This is the safety boundary between the LLM and the database. |
| `app/audit/` | Audit logger, evidence builder, human-review logic | Keeps governance and traceability separate from the agent decision. |
| `app/static/` | Minimal browser page | Lets the project show SSE progress later without building a large frontend. |
| `data/` | Local `aml.db` SQLite file | Runtime/imported data is not application source code. |
| `audit/evidence_logs/` | Final evidence JSON per investigation | Makes evidence packages easy to retrieve and review. |
| `audit/sar_drafts/` | Reserved future SAR-draft output | Mirrors the larger architecture without making SAR generation a current requirement. |

### Python package markers

`app/__init__.py`, `app/agent/__init__.py`, `app/tools/__init__.py`, and `app/audit/__init__.py` mark their directories as Python packages.

They enable clear imports later:

```python
from app.tools.transaction_tools import get_transaction_history
from app.agent.graph import build_investigation_graph
```

They do not contain investigation logic. Their job is to make module organization explicit.

### `requirements.txt`

This file lists packages the project will need. It does not install them itself.

| Dependency | Future use |
| --- | --- |
| `fastapi` | HTTP endpoints such as `/investigate` and audit routes. |
| `uvicorn[standard]` | Local FastAPI server. |
| `pydantic` | Validates request data and final structured verdicts. |
| `langchain` | Standard LLM message and tool abstractions. |
| `langgraph` | Explicit agent/tool state machine. |
| `langchain-core` | Message and tool interfaces imported directly by the application. |
| `langchain-groq` | Groq-specific LangChain `ChatGroq` adapter used by the agent. |
| `python-dotenv` | Loads local configuration from `.env`. |
| `pandas`, `openpyxl` | Available for future CSV/Excel support; the fixed CSV importer currently uses Python's standard `csv` module. |

The version bounds, for example `fastapi>=0.115,<1.0`, allow compatible upgrades but avoid an unreviewed major-version upgrade.

### `.env.example`

`.env.example` is a safe template. It contains placeholders such as:

```env
LLM_PROVIDER=groq
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=llama-3.1-8b-instant
DATABASE_PATH=data/aml.db
DATASET_PATH=
EVIDENCE_LOG_DIR=audit/evidence_logs
SAR_DRAFT_DIR=audit/sar_drafts
```

Later, a developer copies this to `.env` and supplies local values. API keys are never placed in Python code or committed to source control.

### `.gitignore` and `.gitkeep`

`.gitignore` excludes machine-specific or sensitive/generated files:

```text
.env
data/*.db
audit/evidence_logs/*.json
.venv/
__pycache__/
```

`.gitkeep` files preserve empty folders because Git does not track empty directories. They have no Python runtime behavior.

### Phase 1 data flow

There is no live data flow in Phase 1. It only prepares the locations for the later flow:

```text
Provided CSV dataset
    ↓
Dataset understanding and schema design
    ↓
SQLite import
    ↓
Controlled Python tools
    ↓
LangGraph investigation loop
    ↓
SSE updates, audit events, evidence package, human review
```

### Phase 1 test

```powershell
cd C:\Users\hp\Desktop\mini-SAR
Get-ChildItem -Recurse -Force .
```

Expected result: folders, package markers, configuration files, and documentation. At the end of Phase 1 there should be no fake CSV data, no seed script, no FastAPI endpoint, and no agent code.

### Interview explanation

> “Before implementing the AML agent, I separated source code, configuration, imported data, and audit artifacts. I also separated the LLM workflow from controlled database tools, so the model would never gain unrestricted database access.”

---

## Phase 2A — Dataset understanding and data dictionary

### Goal

Understand the user-provided dataset before designing tables or import code. This prevents the project from forcing real source data into assumptions made in advance.

### Dataset used

The reduced, relationship-preserving CSV input directory is:

```text
C:\Users\hp\Desktop\Hackathons\Barclays SAR\files (1)\reduced_50pct
```

| File | Rows | Primary key | Purpose |
| --- | ---: | --- | --- |
| `customers.csv` | 26 | `customer_id` | Customer/KYC, declared income, source of funds, PEP/sanctions/risk context. |
| `accounts.csv` | 27 | `account_id` | Customer account profile, status, activity date, balance baseline. |
| `transactions.csv` | 2,350 | `transaction_id` | Transactional AML evidence. |
| `aml_alerts_history.csv` | 6 | `alert_id` | Earlier alerts, dispositions, SAR outcomes, analyst notes. |
| `watchlists.csv` | 21 | `watchlist_id` | Sanctions/PEP/adverse-media/internal-list screening source. |

### Relationship model discovered

```text
customers.customer_id  (1) ──< accounts.customer_id
customers.customer_id  (1) ──< aml_alerts_history.customer_id
accounts.account_id    (1) ──< transactions.account_id

watchlists.entity_name / aliases
    └── used to screen customers.full_name and transactions.counterparty_name
```

The three actual foreign-key relationships are valid: there are zero retained accounts without a customer, zero transactions without an account, and zero alerts without a customer.

### What each source file contributes

| File | Important investigation fields | What it enables |
| --- | --- | --- |
| `customers.csv` | `full_name`, `occupation`, `annual_income_declared_gbp`, `source_of_funds_declared`, KYC fields, `pep_flag`, `sanctions_flag`, `risk_rating` | Income-mismatch assessment, customer-risk context, KYC controls, customer name screening. |
| `accounts.csv` | `account_status`, `opening_date`, `last_activity_date`, `average_monthly_balance_gbp` | Account age, dormancy/recent activity, balance baseline. |
| `transactions.csv` | time, direction, GBP amount, counterparties, country, channel, payment reference, international/high-risk flags, status | Structuring, rapid movement, counterparty and geographic evidence. |
| `aml_alerts_history.csv` | historical rule, disposition, SAR flag, analyst notes | False-positive context and recurrence history. |
| `watchlists.csv` | entity name, aliases, type, source, list type, score, prohibition, status | Exact, alias, and cautious fuzzy watchlist screening. |

The complete per-column explanation is maintained in [DATA_DICTIONARY.md](DATA_DICTIONARY.md). It documents every field's meaning, source representation, and AML use.

### AML rule fitness

| Rule | Data support | Important qualification |
| --- | --- | --- |
| `RULE-01` Structuring/smurfing | Transaction time, direction, amount, account, and transaction type are available. | The retained set has no cash transaction type, so a result must be called a repeated-credit/structuring pre-signal, not automatically cash structuring. |
| `RULE-02` Rapid movement | Credit/debit direction, time, amount, and counterparty are available. | The retained records are all completed, so status filtering cannot be demonstrated with pending/reversed examples. |
| `RULE-03` Income mismatch | Declared income, occupation, source of funds, transaction credits are available. | Declared income is an indicator, not proof of crime. |
| `RULE-04` Watchlist proximity | Customer/counterparty names, aliases, list type, score, and status are available. | A fuzzy result must be labeled proximity, not a confirmed sanctions match. |

### Data-quality findings

1. Primary keys are unique and all declared source relationships are valid.
2. Account dates use `DD-MM-YYYY`; other source dates are mostly ISO-style. The importer therefore needs explicit per-column date handling.
3. Six transaction `payment_reference` values are blank. This is acceptable because payment narrative is nullable.
4. Six historical `sar_reference` values are blank because all retained alert rows have `sar_filed = False`.
5. Eighteen watchlist `related_entity_id` values are blank. This is valid for standalone listed entities.
6. The reduced alert history contains only `FALSE_POSITIVE` outcomes and no filed SAR. The original full alert history had a true positive and pending outcomes, but they are not in the reduced copy. Therefore the reduced alert history is not a balanced training or evaluation dataset.
7. Alert dates are in 2022–2023, but retained transaction dates are in 2024. Historical alerts must be used as context; they cannot automatically define a matching current transaction window.
8. The source has no `observation_start` or `observation_end` fields. A later investigation request must receive or derive a documented observation window; the system must never invent one silently.
9. The source has `average_monthly_balance_gbp`, not a current account balance. The project must preserve that distinction.
10. Names, birth dates, addresses, IBANs, and analyst notes are sensitive. Future streaming/audit events must expose only evidence necessary for the active investigation.

### Phase 2A test

```powershell
cd C:\Users\hp\Desktop\mini-SAR
Get-Content .\DATA_DICTIONARY.md
```

Expected result: source inventory, relationships, every source field, rule fitness, and data-quality limitations.

### Interview explanation

> “Before writing the schema, I profiled the actual source files, validated the relationships, documented every field, and identified data limitations. That stopped the AML logic from treating missing or weak evidence as if it were reliable evidence.”

---

## Phase 2B — SQLite schema design from the actual dataset

### Goal

Create the empty relational structure that reflects the real CSV field names and relationships. Phase 2B creates tables only; it does not load rows.

### Files created

| File | Purpose |
| --- | --- |
| `app/database.py` | SQLite path resolution, safe connections, schema SQL, database initialization. |
| `SCHEMA_DESIGN.md` | Per-table and per-column explanation of SQLite types, constraints, relationships, and indexes. |
| `data/aml.db` | Local empty SQLite database after initialization. |

### Why source names were preserved

The schema uses actual dataset names instead of generic replacements:

```text
full_name                         not a fabricated name column
account_status                    not a generic status column
average_monthly_balance_gbp       not a misleading current balance column
aml_alerts_history                not a generic alerts table
watchlist_type                    not an assumed risk_type column
```

This matters because a schema should preserve source meaning. Renaming `average_monthly_balance_gbp` to `balance` would make later tool output inaccurate.

### Tables created

| Table | Origin | Purpose |
| --- | --- | --- |
| `customers` | `customers.csv` | Customer/KYC and risk profile. |
| `accounts` | `accounts.csv` | Customer account context. |
| `transactions` | `transactions.csv` | Transaction evidence. |
| `aml_alerts_history` | `aml_alerts_history.csv` | Earlier investigator outcomes and notes. |
| `watchlists` | `watchlists.csv` | Screening reference data. |
| `audit_runs` | Application-owned | One record per investigation lifecycle. |
| `audit_events` | Application-owned | Ordered, safe audit events per investigation. |
| `human_reviews` | Application-owned | Reviewer approval/rejection decisions. |

The three audit tables are not imported from CSV because they are created by the application when investigations run.

### SQLite type decisions

SQLite does not have native Boolean, date, or fixed-decimal types. The schema therefore uses:

| SQLite type | Used for | Reason |
| --- | --- | --- |
| `TEXT` | IDs, names, normalized dates/timestamps, JSON | Stable string representation and readable local storage. |
| `NUMERIC` | GBP amounts and confidence | Numeric comparison/aggregation with readable source values. |
| `INTEGER` | Boolean flags as `0` or `1` | SQLite-compatible Boolean representation. |

Examples of defensive constraints:

```sql
pep_flag INTEGER NOT NULL CHECK (pep_flag IN (0, 1))
amount_gbp NUMERIC NOT NULL CHECK (amount_gbp >= 0)
direction TEXT NOT NULL CHECK (direction IN ('CREDIT', 'DEBIT'))
confidence NUMERIC CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
```

These checks do not decide whether a transaction is suspicious. They only stop structurally invalid values from entering the database.

### Relationships and foreign keys

```text
customers (1) ──< accounts (1) ──< transactions
     │
     └──────────< aml_alerts_history

audit_runs ──< audit_events
     │
     └──────────< human_reviews
```

`app.database.get_connection()` runs this on every connection:

```sql
PRAGMA foreign_keys = ON;
```

This is necessary because SQLite does not automatically enforce foreign keys for every new connection.

`audit_runs.customer_id` is a foreign key to `customers`, but `audit_runs.alert_id` is deliberately plain text. The source alerts are historical; future investigations may be started from a submitted or deterministically derived current alert ID that does not exist in historical alerts.

### Indexes

| Index | Why it is needed later |
| --- | --- |
| `accounts(customer_id)` | Fetch a customer's accounts quickly. |
| `transactions(account_id, transaction_datetime)` | Retrieve bounded transaction windows efficiently. |
| `aml_alerts_history(customer_id, alert_date)` | Retrieve prior alerts chronologically. |
| `audit_runs(started_at)` | List recent investigations. |
| `audit_events(investigation_id, sequence_number)` | Return a chronological audit trail. |
| `human_reviews(investigation_id)` | Retrieve review decisions for an investigation. |

### Important functions in `database.py`

| Function | What it does | Why it matters |
| --- | --- | --- |
| `get_database_path()` | Resolves `DATABASE_PATH` or defaults to `data/aml.db`. | Makes paths predictable regardless of terminal working directory. |
| `get_connection()` | Opens SQLite, enables FK enforcement, returns rows accessible by column name. | Every database tool will use the same safe connection behavior. |
| `initialize_database()` | Creates missing tables and indexes using `CREATE ... IF NOT EXISTS`. | Safe to run repeatedly; it does not delete or seed data. |

### Phase 2B test

```powershell
cd C:\Users\hp\Desktop\mini-SAR
python -m app.database
```

Expected result:

```text
SQLite schema initialized at: C:\Users\hp\Desktop\mini-SAR\data\aml.db
```

The database should contain all eight tables and zero source-data rows before Phase 2C.

### Interview explanation

> “I designed the schema from the actual source fields rather than a generic AML template. I enforced customer-account-transaction integrity through SQLite foreign keys, kept source semantics intact, and separated imported evidence tables from application-owned audit tables.”

---

## Phase 2C — Dataset import pipeline and validation

### Goal

Load the supplied CSV files into SQLite safely and reproducibly. The import must use the approved mapping, normalize values, use parameterized SQL, reject duplicates, and prove that the resulting database matches the source files.

### Files created

| File | Responsibility |
| --- | --- |
| `app/schema_mapper.py` | Source-to-SQLite mapping contract and data normalization. |
| `app/import_data.py` | Atomic import process. |
| `app/validate_dataset.py` | Source and post-import validation summaries. |

### `schema_mapper.py`

This module is the single source of truth for each dataset file. For each mapping it states:

- source file name;
- destination table name;
- expected columns;
- primary key;
- nullable columns;
- numeric columns;
- Boolean columns;
- date and datetime columns.

It is deliberately explicit. It does not guess headers, create substitute values, or silently drop unexpected fields.

#### Key transformations

| Source value | Imported value | Why |
| --- | --- | --- |
| `11-03-2019` in an account date | `2019-03-11` | Normalized dates sort and filter predictably. |
| `True` / `False` | `1` / `0` | SQLite Boolean representation. |
| decimal text such as `75000.0` | validated numeric value | Supports aggregation and threshold checks. |
| blank `payment_reference`, `sar_reference`, `related_entity_id` | `NULL` | Preserves genuine missing values rather than inventing a value. |

Important functions:

| Function | What it does |
| --- | --- |
| `resolve_dataset_path()` | Requires `--dataset-path` or `DATASET_PATH`. |
| `read_source_rows()` | Confirms every required CSV exists and matches approved columns. |
| `normalize_row()` | Converts one row and reports file/row/column context for errors. |
| `parse_boolean()`, `parse_decimal()`, `parse_date()`, `parse_datetime()` | Convert source values safely. |
| `assert_unique_primary_keys()` | Stops before database writes if source IDs are duplicated. |

### `import_data.py`

The importer performs this sequence:

```text
Resolve dataset directory
    ↓
Read and normalize every source file
    ↓
Check source primary-key uniqueness
    ↓
Ensure source-derived SQLite tables are empty
    ↓
Insert rows in foreign-key order, inside one transaction
    ↓
Commit only when every insert succeeds
```

Import order:

```text
customers → accounts → transactions
aml_alerts_history
watchlists
```

Why parameterized SQL matters:

```sql
INSERT INTO transactions (...) VALUES (?, ?, ?, ...)
```

The SQL structure comes from trusted, fixed mappings. CSV values are sent separately as bound parameters through `executemany()`. A counterparty name or payment reference is never string-concatenated into an SQL command.

Why the importer refuses a second import:

It checks whether any source-derived table already has rows. If it does, it fails instead of duplicating or overwriting data. This is intentionally conservative. To test another import, use a separate database path rather than silently deleting existing data.

### `validate_dataset.py`

The validator runs two levels of checking.

#### Source CSV checks

For every file it reports:

- row count;
- duplicate primary-key count;
- missing required values;
- invalid date count;
- invalid Boolean/numeric count.

It also checks the three source relationships:

```text
accounts.customer_id → customers.customer_id
transactions.account_id → accounts.account_id
aml_alerts_history.customer_id → customers.customer_id
```

#### Imported SQLite checks

After import, it:

1. compares each SQLite row count with its CSV row count; and
2. runs `PRAGMA foreign_key_check` so SQLite itself reports relationship violations.

### Actual import result

```text
customers:            26 rows
accounts:             27 rows
transactions:      2,350 rows
aml_alerts_history:    6 rows
watchlists:           21 rows
```

The final validation result was:

```text
All CSV files: PASS
Duplicate IDs: 0
Invalid dates: 0
Invalid values: 0
Broken source relationships: 0
SQLite foreign-key violations: 0
Imported row counts match source row counts
VALIDATION PASSED
```

The normalizations were also checked after import:

```text
Account date range: 2010-04-22 to 2022-04-03
Boolean values: stored as 0/1
Transaction timestamps: 2024-01-01 08:00:00 to 2024-11-28 18:00:00
```

### Phase 2C tests

Run these commands from `C:\Users\hp\Desktop\mini-SAR`.

Validate the source CSV files before importing:

```powershell
python -m app.validate_dataset --dataset-path 'C:\Users\hp\Desktop\Hackathons\Barclays SAR\files (1)\reduced_50pct' --skip-database-check
```

Import the CSV files:

```powershell
python -m app.import_data --dataset-path 'C:\Users\hp\Desktop\Hackathons\Barclays SAR\files (1)\reduced_50pct'
```

Validate source and database together:

```powershell
python -m app.validate_dataset --dataset-path 'C:\Users\hp\Desktop\Hackathons\Barclays SAR\files (1)\reduced_50pct'
```

Expected final line:

```text
VALIDATION PASSED
```

### Interview explanation

> “I built an explicit source-to-SQLite mapping rather than loading CSV data blindly. The importer normalizes date and Boolean fields, uses parameterized SQL, imports in foreign-key order inside one transaction, and refuses duplicate imports. The validator checks source quality, identifiers, relationships, imported row counts, and SQLite foreign-key integrity.”

---

## Status after Phase 2C

At this point, the project has a validated, imported SQLite dataset and an empty audit-table structure. It does **not** yet have:

- AML investigation tools;
- LangChain tool wrappers;
- LangGraph workflow;
- LLM calls;
- FastAPI endpoints;
- SSE streaming;
- audit-event writing or human review endpoints.

Those responsibilities begin in Phase 3 and later phases. Keeping them out of Phases 1–2 makes the foundation explainable: first understand data, then model it, then import and validate it, and only then build the investigation behavior.

---

## Phase 3 — Controlled database tools and deterministic AML signals

### Goal

Create the only approved path from investigation logic to the SQLite database. The tools fetch limited evidence with parameterized SQL and calculate risk pre-signals in Python. They do not expose general SQL, do not return unlimited raw records, and do not ask an LLM to perform arithmetic.

### Why controlled tools matter

The desired security/data-flow boundary is:

```text
Future LLM / LangGraph agent
    ↓ asks for one named tool
Controlled Python tool
    ↓ parameterized, fixed SQL query
SQLite database
    ↓ bounded evidence JSON
Controlled Python tool
    ↓ deterministic calculations already completed
Future LLM / LangGraph agent
    ↓ interprets evidence, never queries the database directly
```

The LLM layer is intentionally not built in this phase. Phase 3 establishes correct Python capabilities first; Phase 5 will wrap these approved functions as LangChain tools for LangGraph.

### Files created

| File | Responsibility |
| --- | --- |
| `app/tools/common.py` | Shared safe customer lookup, date parsing, missing-customer response helpers. |
| `app/tools/customer_tools.py` | `get_customer_profile(customer_id)`. |
| `app/tools/account_tools.py` | `get_account_summary(customer_id)`. |
| `app/tools/transaction_tools.py` | `get_transaction_history(customer_id, observation_start, observation_end)` and deterministic AML calculations. |
| `app/tools/alert_tools.py` | `get_prior_alert_history(customer_id)`. |
| `app/tools/watchlist_tools.py` | `screen_watchlist(customer_id)`. |

### Shared safety behavior

All tools:

- use `app.database.get_connection()`, which enables SQLite foreign keys;
- use bound parameters such as `WHERE customer_id = ?`, never SQL built from an input value;
- return ordinary JSON-ready dictionaries, making later audit logging straightforward;
- return a safe `found: false` result for an unknown customer instead of exposing an exception or arbitrary query path;
- support an optional `database_path` only for isolated testing; the future LLM-facing interface will not expose database-path control.

### Tool 1 — `get_customer_profile(customer_id)`

This tool returns the bounded customer/KYC fields needed for investigation:

```text
occupation, employer_name, declared annual income, declared source of funds,
KYC status/review/expiry, PEP flag, sanctions flag, risk rating,
country of residence, address country
```

It intentionally does **not** return date of birth, detailed address, or every customer column. Those fields are sensitive and are not necessary for the planned AML signals.

Data flow:

```text
customer_id → SELECT named columns FROM customers WHERE customer_id = ? → profile JSON
```

### Tool 2 — `get_account_summary(customer_id)`

This tool returns all accounts for one known customer, but omits the sensitive IBAN because it is not needed for the mini investigation.

For every account it calculates:

```text
days_since_last_activity = reference date − last_activity_date
```

The optional `as_of_date` exists for reproducible tests. If omitted, the tool uses the current date. If source activity appears later than the reference date, the result is capped at zero rather than producing a misleading negative number.

Returned account evidence includes:

```text
account ID, account type, currency, account status, opening date,
last activity date, average monthly balance, days since last activity
```

### Tool 3 — `get_transaction_history(customer_id, observation_start, observation_end)`

This is the core deterministic AML tool. It requires an explicit ISO date window (`YYYY-MM-DD`) because Phase 2A showed that the dataset does not contain ready-made observation-window columns.

The SQL query:

- joins `transactions` to `accounts` to obtain the customer relationship;
- filters to the selected customer;
- filters to `COMPLETED` transactions;
- filters to the requested time range;
- orders results by transaction time;
- never returns unlimited raw history to the future LLM.

#### Summary calculations

```text
total_credits       = sum of CREDIT amounts in the window
total_debits        = sum of DEBIT amounts in the window
transaction_count   = count of completed transactions in the window
net_retained_amount = max(total_credits − total_debits, 0)
retention_ratio     = net_retained_amount / total_credits
```

The retention ratio is a window-based movement indicator. It is **not** called an account balance because the source dataset contains average monthly balance, not a current balance.

#### Rule 1 pre-signal — structuring/repeated near-threshold credits

The policy constants are explicit Python values:

```text
Reporting threshold:                 £10,000
Near-threshold range:                £8,000 to less than £10,000
Rolling observation period:          7 days
Minimum near-threshold credit count: 3
```

The tool finds credits in that range and searches for the largest seven-day rolling window. It returns:

- Boolean `structuring_presignal`;
- candidate count and largest rolling-window count;
- relevant transaction IDs and amounts;
- the exact thresholds used.

This is a pre-signal, not a conclusion. The LLM later explains the pattern and considers any benign evidence.

#### Rule 2 pre-signal — rapid movement of funds

The tool compares credits and later debits on the same account.

A rapid-outflow pair is defined as:

```text
debit occurs within 2 days after a credit
and debit amount is at least 80% of the credit amount
```

It returns a Boolean, pair count, up to five evidence pairs, time between the movements, counterparty name, and relevant transaction IDs.

#### Rule 3 pre-signal — income mismatch

The tool retrieves the customer’s declared annual income and compares it with credits in the selected window.

```text
income_mismatch = total credits >= 50% of declared annual income
```

It returns the declared income, credit-to-income ratio, threshold, and Boolean result. This is deliberately deterministic and transparent. It is not evidence of crime on its own: declared income may be incomplete, outdated, or not representative of legitimate wealth.

#### Bounded important transactions

The tool selects at most twelve transactions:

1. signal-linked structuring transactions first;
2. signal-linked rapid-outflow transactions next;
3. highest-value remaining transactions until the cap is reached.

The returned record includes only relevant evidence fields such as transaction ID, account, time, direction, GBP amount, counterparty, country, channel, cross-border/high-risk flags, and status. It excludes unlimited raw transaction history and payment narratives.

### Tool 4 — `get_prior_alert_history(customer_id)`

This tool retrieves at most ten prior alerts in reverse chronological order. It returns:

- historical alert ID/date/type/rules;
- prior disposition;
- SAR filed flag/reference;
- prior analyst notes;
- an explicit `sar_previously_filed` Boolean;
- a separate `false_positive_context` list for earlier false-positive notes.

Why it matters: a large transaction or repeated alert is not automatically suspicious. Previous legitimate explanations and prior dispositions must be considered by the final investigator reasoning.

### Tool 5 — `screen_watchlist(customer_id)`

This tool screens the customer name and every distinct counterparty name associated with that customer. It does not return all counterparties; it returns only bounded matches.

Matching methods:

| Method | Rule |
| --- | --- |
| `exact` | Normalized candidate name equals normalized `entity_name`. |
| `alias` | Normalized candidate name equals a normalized alias. Pipe and semicolon-separated aliases are supported. |
| `fuzzy_token_jaccard` | Token-set Jaccard similarity is at least `0.60`. |

Name normalization lowercases text, removes punctuation, and compares alphanumeric name tokens. Exact and alias matches receive a score of `1.0`; fuzzy matches return their actual Jaccard score.

The tool screens only `ACTIVE` and `UNDER_REVIEW` watchlist records, sorts stronger/riskier matches first, and returns at most ten matches. A fuzzy match is explicitly called **proximity**, not a confirmed sanctions hit.

### Error handling

Examples of safe boundary results:

```json
{
  "customer_id": "CUST-NOT-FOUND",
  "found": false,
  "message": "No customer exists for the supplied customer_id."
}
```

```json
{
  "customer_id": "CUST-UK-050012",
  "found": false,
  "error": "observation_start must be on or before observation_end."
}
```

The future graph can log and interpret these structured failures without exposing stack traces or database internals.

### Phase 3 test results

The tools were run against the imported SQLite dataset with a fixed test window.

```text
Customer profile: found, LOW risk, VERIFIED KYC
Account summary: 1 account; 27 days since last activity as of 2024-12-01
Transaction window: 93 transactions
Credits: £75,000.00
Debits: £20,955.73
Retention ratio: 0.7206
Income mismatch: true
Important transaction records returned: 12
Prior alerts returned: 1
Prior SAR filed: false
```

The safety and screening tests also passed:

```text
Unknown customer → safe found:false response
Invalid date window → safe validation error
Retained watchlist case → one alias match returned
```

### How to test Phase 3

From `C:\Users\hp\Desktop\mini-SAR`:

```powershell
python -m compileall app
```

Expected result: all modules under `app/tools/` compile successfully.

Then run a reproducible smoke test:

```powershell
@'
from app.tools.account_tools import get_account_summary
from app.tools.alert_tools import get_prior_alert_history
from app.tools.customer_tools import get_customer_profile
from app.tools.transaction_tools import get_transaction_history
from app.tools.watchlist_tools import screen_watchlist

customer_id = "CUST-UK-050012"
print(get_customer_profile(customer_id))
print(get_account_summary(customer_id, as_of_date="2024-12-01"))
print(get_transaction_history(customer_id, "2024-01-01", "2024-12-31"))
print(get_prior_alert_history(customer_id))
print(screen_watchlist(customer_id))
'@ | python -
```

Expected result: five JSON-ready dictionaries; transaction output must contain no more than twelve `important_transactions`.

### Interview explanation

> “I gave the future agent five narrowly scoped Python tools rather than database access. Each tool uses fixed, parameterized SQL and returns bounded evidence. Risk signals such as structuring, rapid movement, and income mismatch are deterministic Python calculations with documented thresholds. The LLM will only interpret those outputs, which reduces hallucination and makes every conclusion auditable.”
---

## Phase 4 — Audit logger and evidence package

### Goal

Phase 4 creates a durable investigation history and one self-contained evidence JSON file per completed run. It records safe operational facts—tool calls, tool results, summaries, verdicts, and later human reviews—not private LLM chain-of-thought.

### Files created

| File | Purpose |
| --- | --- |
| `app/audit/audit_logger.py` | Creates runs, appends ordered events, completes/fails a run, and retrieves audit records. |
| `app/audit/evidence_builder.py` | Builds and atomically saves evidence packages. |

### Audit lifecycle

```text
Alert accepted
  -> create_investigation_run()
  -> INVESTIGATION_STARTED event, sequence 1
  -> TOOL_CALLED / TOOL_RESULT / ANALYSIS_SUMMARY events
  -> complete_investigation_run()
  -> VERDICT_FINALIZED event
  -> save_evidence_package()
  -> EVIDENCE_PACKAGE_SAVED event
```

`audit_runs` stores one row per investigation: investigation ID, alert ID, customer ID, start/completion times, status, verdict, confidence, provider, and model name.

`audit_events` stores the ordered details: event ID, investigation ID, sequence number, event type, UTC timestamp, and JSON payload. The unique `(investigation_id, sequence_number)` pair makes the order durable even if timestamps are close together.

### `audit_logger.py`

`create_investigation_run()` generates an `INV-...` ID unless a controlled test ID is supplied, inserts a `RUNNING` record, and writes `INVESTIGATION_STARTED`. The customer ID is a foreign key, so a run cannot be created for an unknown customer. The alert ID remains plain text because a later submitted alert might not exist in the historical-alert table.

`append_audit_event()` verifies that the run exists, starts a SQLite immediate transaction, calculates the next sequence number, serializes a safe caller-provided payload to JSON, and writes the event. A tool event should contain a short summary such as transaction count or signal result—not private model reasoning.

`complete_investigation_run()` accepts only `TRUE_POSITIVE` or `FALSE_POSITIVE` and a confidence from 0 to 1. It changes the run to `COMPLETED` and logs `VERDICT_FINALIZED`. `fail_investigation_run()` marks a running record as `FAILED` and logs only a safe error summary, never a traceback or secret.

An important SQLite lesson: a connection context manager commits or rolls back but does not automatically guarantee closure. The internal `_audit_connection()` helper therefore always commits on success, rolls back on error, and closes the database connection. This prevents old audit connections from holding write locks.

### `evidence_builder.py`

The final evidence JSON contains:

```text
investigation ID and generation time
audit-run metadata
original alert
all tool outputs actually used
final verdict
key evidence
false-positive factors considered
chronological audit events
```

The file is saved to `audit/evidence_logs/{investigation_id}.json`. `_atomic_json_write()` writes a temporary file first and then uses `os.replace()` to avoid leaving a half-written JSON file after interruption.

The builder writes twice for an important reason:

1. it atomically creates the initial evidence file;
2. it logs `EVIDENCE_PACKAGE_SAVED` only after that file exists;
3. it rebuilds and atomically rewrites the package so the final file includes its own save event.

### Phase 4 test

A labelled structural test used `TEST-PHASE4-AUDIT`, an actual imported customer/alert, and a clearly marked test-only verdict. It was not treated as an AML decision.

The verified event order was:

```text
1 INVESTIGATION_STARTED
2 TOOL_CALLED
3 TOOL_RESULT
4 ANALYSIS_SUMMARY
5 VERDICT_FINALIZED
6 EVIDENCE_PACKAGE_SAVED
```

The evidence JSON existed, contained all six events, and contained the original alert. Afterwards, the exact test run, its events, and its test evidence file were removed. Imported AML data was not changed.

### How to test

```powershell
cd C:\Users\hp\Desktop\mini-SAR
python -m compileall app\audit
```

Expected result: `audit_logger.py` and `evidence_builder.py` compile. A repeat lifecycle test should use a unique `TEST-...` ID and remove only that exact run, its events, and evidence file after verification.

### Interview explanation

> “Every investigation receives a durable run record and ordered audit events. I store safe operational evidence rather than hidden model reasoning. Once complete, the system atomically writes an evidence package containing the original alert, actual tool outputs, final verdict, false-positive factors, and chronology, so an auditor can reconstruct what happened.”
---

## Phase 5 — LangChain and LangGraph investigation agent

### Goal

Phase 5 connects the evidence tools to a controlled model loop. The model decides which allow-listed tool is needed next and interprets its bounded result, while Python enforces tool scope, deterministic calculations, stopping limits, verdict validation, and audit-safe events.

### Files created or updated

| File | Purpose |
| --- | --- |
| `app/agent/state.py` | Typed LangGraph state plus Pydantic verdict/evidence schemas. |
| `app/agent/prompts.py` | Evidence, tool-use, checkpoint, and final-output rules. |
| `app/agent/llm.py` | Environment-based, Groq-only `ChatGroq` configuration and tool binding. |
| `app/agent/graph.py` | LangChain wrappers, `agent_node`, `tools_node`, conditional routing, and graph compilation. |
| `.env.example` | Groq provider/key/model placeholders plus iteration and recursion limits. |
| `requirements.txt` | Version ranges aligned with installed LangChain 1.x and LangGraph 1.x. |

### Architecture

```text
START
  -> agent_node
       -> one valid tool call -> tools_node
              -> parameterized Python tool
              -> ToolMessage + audit-safe events
              -> agent_node
       -> valid FinalVerdict -> END
```

LangGraph is useful here because state, node responsibilities, looping, and the terminal condition are explicit. The graph cannot silently invoke an arbitrary function or stop with an unvalidated text answer.

### State design

`InvestigationState` contains:

```text
messages             reducer-managed LangChain message history
alert                original submitted alert
customer_id          fixed investigation scope
investigation_id     audit correlation ID
tool_results         executed tool arguments and results
audit_event_queue    ordered events later streamed by SSE
final_verdict        validated terminal verdict or null
system_prompt_logged whether prompt setup was already audited
agent_iterations     explicit model-call counter
```

The `messages` field uses LangGraph's `add_messages` reducer, so each node returns only new messages and LangGraph appends them correctly. The audit queue uses list addition for the same reason.

### Structured verdict validation

Pydantic models define the terminal contract:

```text
FinalVerdict
  verdict: TRUE_POSITIVE or FALSE_POSITIVE
  confidence: 0 to 1
  rules_triggered: only RULE-01 through RULE-04
  key_evidence[]
    rule_mapped
    finding
    supporting_data
      amounts[]
      transaction_ids[]
      counterparties[]
      source_table
    statistical_context
  false_positive_factors_considered[]
  final_reasoning
```

Extra fields are forbidden. A malformed verdict, invalid confidence, or unknown rule is rejected rather than saved as a result.

### Prompt design

The system prompt requires the model to:

- use only the submitted alert and returned tool evidence;
- never invent records, amounts, names, dates, watchlist hits, or analyst notes;
- never write SQL or request direct database access;
- interpret Python-computed pre-signals without replacing their thresholds;
- distinguish fuzzy proximity from confirmed watchlist matching;
- consider prior false-positive context;
- produce concise visible summaries rather than chain-of-thought;
- request no more than one tool per turn and never repeat a completed call.

Before the first tool, content must include `INITIAL HYPOTHESIS` and `NEXT STEP`. When another tool is needed after a result, content must include `ANALYSIS SUMMARY`, `UPDATED HYPOTHESIS`, and `NEXT STEP`. When the model finalizes immediately after a tool, the graph creates a safe final `analysis_summary` event from the validated `final_reasoning` before emitting the verdict.

### LangChain tool wrappers

The model sees exactly five wrapper schemas:

```text
get_customer_profile(customer_id)
get_account_summary(customer_id)
get_transaction_history(customer_id, observation_start, observation_end)
get_prior_alert_history(customer_id)
screen_watchlist(customer_id)
```

Internal testing parameters such as `database_path` and `as_of_date` are not exposed. The wrappers call the Phase 3 Python functions; therefore the model still has no SQL interface.

### Model configuration

The Phase 5 configuration was corrected to use Groq only. `build_bound_model()`
creates `ChatGroq` with:

```text
model name read from GROQ_MODEL
API key read from GROQ_API_KEY
five allow-listed local tools
parallel tool calls disabled
temperature 0 for lower output variability
60-second request timeout
two transient retries
```

`LLM_PROVIDER` is also read from `.env` and must equal `groq`. No model name is
hardcoded in Python, and no fallback silently chooses a model. This matters
because model availability can differ by Groq account and change over time.

Provider-native strict structured output is not combined with tool use here.
Groq documents that structured-output support varies by model and that strict
structured outputs cannot currently be combined with tool use. The graph
therefore uses ordinary Groq tool calling while investigating; its final prompt
requires JSON, and `_extract_final_verdict()` validates the terminal JSON with
the Pydantic `FinalVerdict` schema before the graph may end.

The API key is stored in the frozen `LLMSettings` object with `repr=False`, so
printing the settings object does not reveal the credential.

### Why the graph limits are loaded separately

`load_llm_settings()` requires the Groq provider, key, and model because it is
used for a live model. `load_graph_limits()` reads only
`AGENT_MAX_ITERATIONS` and `LANGGRAPH_RECURSION_LIMIT`.

This separation lets an offline test inject a scripted model and exercise the
real graph without requiring or pretending to use a live API credential.

### `agent_node`

The agent node logs prompt setup once, enforces the model-iteration limit, calls the bound model, validates checkpoint labels on tool-planning responses, and then does one of two things:

1. returns the model's `AIMessage` containing one tool call; or
2. extracts and validates `FinalVerdict`, queues a safe final assessment, and stores the verdict in state.

### `tools_node`

The tools node verifies:

- the requested name is in the five-tool registry;
- exactly one tool was requested;
- tool `customer_id` equals the alert customer;
- transaction dates exactly equal the alert observation window;
- the same tool/argument combination was not already executed.

It logs `TOOL_CALLED`, invokes the wrapper, catches errors as safe structured results, logs `TOOL_RESULT`, stores the result in state, and creates a `ToolMessage` linked to the original tool-call ID.

### Stopping controls

`AGENT_MAX_ITERATIONS` limits model calls, while LangGraph's `recursion_limit` limits graph super-steps. These are separate protections: the first expresses application policy and the second prevents an accidental graph loop.

### Phase 5 offline tests

No Groq request was needed for structural testing. A scripted model requested a real transaction tool, received actual bounded SQLite evidence, and then returned a schema-valid verdict.

Verified result:

```text
final verdict: TRUE_POSITIVE
confidence: 0.72
tool results stored: 1
important transactions returned: 12
agent iterations: 2
```

Verified stream/audit queue order:

```text
system_prompt_built
analysis_summary
tool_call
tool_result
analysis_summary
verdict
```

Boundary tests proved that only the five intended argument schemas are exposed, a different customer ID is blocked, a different observation window is blocked, and an invalid structured verdict is rejected.

### How to test

```powershell
cd C:\Users\hp\Desktop\mini-SAR
python -m compileall app\agent app\tools
```

Expected result: all Phase 5 modules compile. A live model test additionally
requires copying `.env.example` to `.env`, setting a real `GROQ_API_KEY`, and
selecting a `GROQ_MODEL` available in your Groq account. Secrets must never be
committed.

---

## Phase 5 setup correction — Groq and VS Code imports

### Why this correction was needed

The first Phase 5 version used `ChatOpenAI` and an OpenAI-specific hardcoded
default. That did not match the intended runtime. The project now deliberately
supports one provider—Groq—so the interview story and the implementation stay
small and consistent.

Hardcoding a model is undesirable because availability, capability, limits, and
account access can change independently of the source code. Environment
configuration separates these deployment choices from application behavior.
The `.env.example` file documents the names, while the ignored `.env` stores the
real local key.

Pylance import errors commonly occur when VS Code analyzes the project with a
different Python interpreter from the terminal. Installing a package globally,
in another virtual environment, or in an unselected Conda environment does not
make it visible to the selected VS Code interpreter.

### Files changed

| File | Correction |
| --- | --- |
| `app/agent/llm.py` | Replaced `ChatOpenAI` with `ChatGroq`; added strict Groq-only environment validation; removed every hardcoded model. |
| `app/agent/graph.py` | Corrected the provider description and loads credential-free graph limits for offline tests. |
| `requirements.txt` | Replaced `langchain-openai` with `langchain-groq` and explicitly listed directly imported `langchain-core`. |
| `.env.example` | Added `LLM_PROVIDER`, `GROQ_API_KEY`, and `GROQ_MODEL`. |
| `.vscode/settings.json` | Added the workspace import root and project-local virtual-environment path. |

The package markers already existed at `app/__init__.py`,
`app/agent/__init__.py`, `app/tools/__init__.py`, and
`app/audit/__init__.py`. `app/static` contains browser assets, not Python
modules, so it does not need `__init__.py`.

### Create and activate the environment on Windows PowerShell

Open `C:\Users\hp\Desktop\mini-SAR` as the VS Code folder, then run:

```powershell
cd C:\Users\hp\Desktop\mini-SAR
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

After activation, the prompt normally starts with `(.venv)`. Verify which
interpreter PowerShell is using:

```powershell
python -c "import sys; print(sys.executable)"
```

Expected path:

```text
C:\Users\hp\Desktop\mini-SAR\.venv\Scripts\python.exe
```

If PowerShell blocks `Activate.ps1`, allow scripts only for the current shell
session and retry activation:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

This does not change the permanent machine or user execution policy.

### Select the VS Code interpreter

1. Open the `mini-SAR` project folder itself in VS Code.
2. Press `Ctrl+Shift+P`.
3. Run `Python: Select Interpreter`.
4. Choose `.venv\Scripts\python.exe`.
5. If diagnostics remain stale, run `Developer: Reload Window`.

`python.defaultInterpreterPath` gives a new workspace the expected `.venv`
location. The explicit interpreter selection remains the authoritative VS Code
choice. `python.analysis.extraPaths: ["./"]` tells Pylance that the opened
project root contains the `app` package.

### Verify imports

With the virtual environment active:

```powershell
python -c "import langchain_core, langgraph, langchain_groq, dotenv, pydantic; from langchain_groq import ChatGroq; print('All imports OK:', ChatGroq.__name__)"
python -m pip check
python -m compileall -q app
```

Expected output:

```text
All imports OK: ChatGroq
No broken requirements found.
```

`compileall -q` is silent on success. It checks Python syntax but does not call
Groq.

### Configure a live model

Create the ignored `.env` file:

```powershell
Copy-Item .env.example .env
```

Then replace only the placeholder key and choose a model currently available in
your Groq account:

```env
LLM_PROVIDER=groq
GROQ_API_KEY=your_real_key_here
GROQ_MODEL=llama-3.1-8b-instant
```

The model shown here is configuration, not a Python default. It can be replaced
without changing application code.

### Interview question this correction answers

> “How do you keep an agent portable and secure across model deployments?”

Answer: the graph depends on LangChain message/tool interfaces, while the
provider adapter is isolated in `llm.py`. Provider, credential, and model are
validated environment configuration; secrets and deployment choices are not
hardcoded. A project-local virtual environment makes the runtime reproducible,
and Pydantic still validates the final verdict independently of the model.

### Interview explanation

> “I used LangGraph to make the investigation loop explicit: the agent can request one allow-listed tool, the tools node enforces customer and date-window scope, and the result returns as a ToolMessage. Python calculates the AML signals, while the model only interprets evidence. The graph stops only on a Pydantic-validated verdict, has iteration and recursion limits, and emits safe structured summaries rather than chain-of-thought.”

---

## Phase 5 checkpoint — End-to-end Groq agent classification test

### Goal and boundary

This is an intermediate validation checkpoint, not Phase 6. It answers three
questions before the production-style API and SSE lifecycle are added:

1. Can the application authenticate to the configured Groq model?
2. Can the LangGraph agent gather evidence through all five controlled tools?
3. Does the Pydantic-validated verdict match an evidence-backed expected label?

The checkpoint uses normal JSON for `/test-investigate`. The browser shows the
returned events in order after the request completes. True SSE streaming,
durable audit-run creation, evidence-file saving, audit retrieval, and human
review remain later phases.

Checkpoint runs use `persist_audit=False`. This prevents repeated model
experiments from being confused with completed audited investigations.

### Files created or changed

| File | What changed and why |
| --- | --- |
| `app/api.py` | Added the temporary test API, server-owned fixture registry, safe event translation, expected/actual comparison, and mismatch reporting. |
| `app/static/index.html` | Added the minimal model-test and two-alert browser interface. |
| `app/agent/llm.py` | Added `build_chat_model()` so `/test-model` can probe Groq without binding investigation tools. |
| `app/agent/prompts.py` | Requires all five evidence tools once and corrects the final-output instruction for Groq JSON plus Pydantic validation. |
| `app/agent/graph.py` | Adds safe visible-summary fallback for tool calls with empty prose and strict handling of one complete JSON code fence. |
| `Phases.md` | Documents the checkpoint, data basis, flow, tests, and interview explanation. |

No database row was added or changed.

### Dataset-backed test fixtures

The test alert IDs are clearly marked fixture identifiers. They exist only in
Python memory and are never inserted into SQLite. The referenced customers,
profiles, transactions, prior alerts, counterparties, and watchlist rows all
come from the imported user-provided dataset.

#### Expected true positive

```text
fixture_id: true_positive
customer_id: CUST-UK-004821
window: 2024-11-07 through 2024-11-14
expected verdict: TRUE_POSITIVE
```

The controlled tools found:

- 22 credits between £8,000 and £10,000 in the structuring window;
- deterministic `structuring_presignal = true`;
- deterministic `rapid_outflow_detected = true`;
- deterministic `income_mismatch = true`;
- declared annual income of £22,000;
- an alias match between an existing counterparty and an active sanctions
  watchlist entry.

#### Expected false positive

```text
fixture_id: false_positive
customer_id: CUST-UK-050012
window: 2024-10-01 through 2024-10-31
expected verdict: FALSE_POSITIVE
```

The controlled tools found:

- declared annual income of £90,000;
- ordinary monthly activity in the selected October window;
- no structuring pre-signal;
- no rapid-outflow pre-signal;
- no income-mismatch pre-signal;
- no watchlist match;
- an existing prior alert disposed as false positive.

The expected verdict is stored beside each server fixture but is removed before
the alert is passed to LangGraph. The model receives the alert and must discover
the evidence through tools; it does not receive the answer key.

These labels are checkpoint expectations, not regulatory ground-truth
certification. A mismatch is useful test evidence and is never hidden.

### `GET /test-model`

This endpoint:

1. loads `LLM_PROVIDER`, `GROQ_API_KEY`, and `GROQ_MODEL`;
2. creates an unbound `ChatGroq` instance;
3. sends `Reply with only: MODEL_CONNECTED`;
4. strips surrounding whitespace;
5. reports success only if the content is exactly `MODEL_CONNECTED`.

No investigation tools are supplied to this probe. The API key is never
returned. Configuration, authentication, rate-limit, and unsupported-model
errors are converted to concise browser-safe messages.

Successful shape:

```json
{
  "status": "success",
  "model": "value from GROQ_MODEL",
  "provider": "groq",
  "response": "MODEL_CONNECTED",
  "events": []
}
```

### `GET /test-alerts`

This route returns both fixture descriptions. Before returning them, it verifies
that each customer exists and that the configured observation window contains
transactions.

The frontend displays the expected labels because selecting a labeled test case
is the purpose of this benchmark. The POST route accepts only `fixture_id`, so a
browser cannot replace the expected verdict or alter customer/date scope.

### `POST /test-investigate`

Request:

```json
{
  "fixture_id": "true_positive"
}
```

Data flow:

```text
fixture_id
  -> server-owned fixture lookup
  -> expected label kept outside model alert
  -> create_initial_state()
  -> LangGraph agent_node
  -> exactly one allow-listed tool request
  -> tools_node validates customer and observation window
  -> controlled Python/SQLite tool
  -> ToolMessage returned to agent
  -> repeat until all five evidence tools are complete
  -> terminal JSON
  -> Pydantic FinalVerdict validation
  -> Python expected/actual comparison
  -> ordered JSON response
```

The endpoint additionally checks that all five tool names appear exactly once
in `tool_results` and that none returned an error. A model that guesses the
correct verdict without completing the evidence checklist fails the checkpoint.

For `get_account_summary`, the tools node supplies the server-owned
`observation_end` as the internal activity-age reference date. This prevents a
historical 2024 test from being judged against today's date. The model-facing
tool still accepts only `customer_id`, so the model cannot alter the reference
date.

### Visible events and chain-of-thought boundary

The graph's safe event queue is translated into objects such as:

```json
{
  "event_type": "tool_call",
  "message": "TOOL_CALLED: get_transaction_history",
  "payload": {
    "tool": "get_transaction_history",
    "args": {}
  }
}
```

The ordered output includes:

```text
investigation_started
alert_loaded
agent_started
initial_hypothesis
tool_call
tool_result
analysis_summary
verdict
verdict_match_check
investigation_completed
```

Groq provider reasoning fields are not read, returned, or stored. Only ordinary
assistant content explicitly formatted as investigator-facing checkpoints is
shown.

Some tool-calling models return a valid tool call with empty assistant content.
In that case, Python creates a conservative checkpoint stating only which
controlled results have been received and which tool is next. It never invents
an evidentiary conclusion from hidden reasoning.

### Verdict matching

Python performs:

```python
matched_expected = actual_verdict == expected_verdict
```

If the labels differ, the response preserves:

- `expected_verdict`;
- `actual_verdict`;
- `matched_expected: false`;
- the complete visible event sequence;
- the final validated JSON;
- a limited possible-reason message.

The possible-reason logic first checks for tool errors and missing tools. If all
tools completed, it states only that model interpretation differed and directs
the investigator to the visible summaries, tool evidence, and
`final_reasoning`. It does not claim access to an unobserved cause.

### Minimal frontend behavior

The page contains:

- heading `Mini AML SAR Investigator — Agent Test`;
- `Test Model Connection` button;
- two-option alert dropdown;
- `Run Investigation` button;
- ordered event panel;
- final verdict JSON panel;
- explicit match/mismatch status.

JavaScript uses `textContent` when rendering model/tool data rather than
inserting it as HTML. This prevents returned strings from becoming executable
page markup.

### How to run

```powershell
cd C:\Users\hp\Desktop\mini-SAR
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` and replace the placeholder with a real Groq key. Then:

```powershell
uvicorn app.api:app --reload
```

Open:

```text
http://127.0.0.1:8000/
```

Expected manual sequence:

1. Click `Test Model Connection`.
2. Confirm `MODEL_CONNECTED`.
3. Select `TRUE_POSITIVE test alert`.
4. Click `Run Investigation`.
5. Review five tool calls, five bounded results, summaries, and verdict match.
6. Select `FALSE_POSITIVE test alert` and repeat.

### Optional API-only tests

```powershell
Invoke-RestMethod http://127.0.0.1:8000/test-model |
    ConvertTo-Json -Depth 10

Invoke-RestMethod http://127.0.0.1:8000/test-alerts |
    ConvertTo-Json -Depth 10

Invoke-RestMethod `
    -Method Post `
    -Uri http://127.0.0.1:8000/test-investigate `
    -ContentType "application/json" `
    -Body '{"fixture_id":"true_positive"}' |
    ConvertTo-Json -Depth 30
```

Replace `true_positive` with `false_positive` for the second test.

### Automated verification performed

An offline scripted-model integration test exercised:

```text
GET /                         -> 200 and HTML
GET /test-model              -> 200 and MODEL_CONNECTED
GET /test-alerts             -> 200 and two fixtures
POST TP /test-investigate    -> 200, five calls/results, matched true
POST FP /test-investigate    -> 200, five calls/results, matched true
```

The scripted verdicts verify routing and response construction only. They do not
measure Groq model accuracy. A live connection was not attempted because no
`.env` containing the user's Groq credential exists.

### Interview question this checkpoint answers

> “How did you validate the agent before adding production API streaming?”

Answer: isolate model connectivity, tool orchestration, and verdict quality in a
small benchmark. Use real dataset rows and deterministic tools, keep expected
labels outside model context, require the complete evidence checklist, validate
the terminal schema in Python, preserve mismatches, and expose safe summaries
instead of chain-of-thought.
