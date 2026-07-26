# Mini AML SAR Investigator — Learning Notes by Phase

This document is the single theory guide for the phases completed so far. It explains not only *what* was created, but *why* it exists, how data flows through it, how to test it, and how to explain the decisions in an interview.

Completed phases:

1. Phase 1 — Project setup and boundaries
2. Phase 2A — Dataset understanding and data dictionary
3. Phase 2B — SQLite schema design from the actual dataset
4. Phase 2C — CSV import pipeline and validation

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
| `langchain-openai` | LangChain connection to an OpenAI model in the later agent phase. |
| `python-dotenv` | Loads local configuration from `.env`. |
| `pandas`, `openpyxl` | Available for future CSV/Excel support; the fixed CSV importer currently uses Python's standard `csv` module. |

The version bounds, for example `fastapi>=0.115,<1.0`, allow compatible upgrades but avoid an unreviewed major-version upgrade.

### `.env.example`

`.env.example` is a safe template. It contains placeholders such as:

```env
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
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
Get-ChildItem -Recurse -Force .\mini-sar
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
Get-Content .\mini-sar\DATA_DICTIONARY.md
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
cd .\mini-sar
python -m app.database
```

Expected result:

```text
SQLite schema initialized at: ...\mini-sar\data\aml.db
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

Run these commands from `C:\Users\hp\Desktop\mini-SAR\mini-sar`.

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
