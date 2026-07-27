# Mini AML SAR Investigator — Implementation Plan

## Phase 0 scope

This document is the approved build plan. Phase 0 intentionally creates no application code, database, dependency file, or runtime configuration. Each later phase will be implemented, explained, and tested before proceeding to the next one.

## 1. Project objective and design boundaries

The project is a compact, inspectable AML investigation service. An analyst submits a pre-defined alert. The system gathers bounded evidence through controlled Python tools, calculates deterministic risk indicators, asks an LLM to interpret those tool results, and returns a structured true-positive or false-positive verdict. The workflow records what happened in an audit trail and supports a separate human-review decision.

The key boundary is:

`LLM -> tool request -> controlled Python function -> SQLite -> bounded result -> LLM interpretation`

The LLM will never receive database credentials or SQL execution capability. It will not calculate AML signals from arbitrary raw data; Python will do that deterministically. The stream will expose event summaries and structured evidence, never private chain-of-thought.

## 2. Technology stack and why it is used

| Technology | Role | Why it fits this mini project |
| --- | --- | --- |
| Python 3.11+ | Application language | Clear, widely used for APIs, data processing, and AI orchestration. |
| FastAPI | HTTP API | Gives typed request/response models, simple routing, and async streaming support. |
| SQLite (`sqlite3`) | Local relational database | A zero-infrastructure, auditable data store that still demonstrates real SQL data modeling. |
| LangChain | Tool and message abstractions | Provides a standard way to describe controlled functions as LLM-callable tools. |
| LangGraph | Investigation state machine | Makes the agent/tool loop, state, and stop condition explicit and easy to explain in an interview. |
| Groq-hosted open model through LangChain `ChatGroq` | Evidence interpretation | Produces investigation summaries and the final JSON verdict constrained to tool evidence. Provider, API key, and model are read from environment variables. |
| Server-Sent Events (SSE) | Live investigation updates | Streams one-way, ordered browser updates over standard HTTP without a WebSocket frontend. |
| Pydantic | Request, response, and verdict validation | Ensures alerts, human reviews, and final verdicts have predictable shapes. |
| Plain HTML/JavaScript | Minimal demo UI | Keeps the focus on backend architecture while showing a live SSE investigation. |

The project will use no vector database and no retrieval-augmented generation. This is structured data retrieval via allow-listed tools, which is the correct fit for transactional AML evidence.

## 3. Target folder structure

```text
mini-sar-investigator/
├── implementation.md              # This plan and phase-by-phase learning guide
├── app/
│   ├── api.py                     # FastAPI application, routes, and SSE orchestration
│   ├── database.py                # SQLite connection, schema initialization, query helpers
│   ├── import_data.py             # Imports user-provided CSV/Excel sources into SQLite
│   ├── validate_dataset.py         # Validates the imported dataset and prints a summary
│   ├── schema_mapper.py            # Maps source columns to investigation concepts when needed
│   ├── agent/
│   │   ├── state.py               # LangGraph state and investigation data models
│   │   ├── graph.py               # Agent/tools graph nodes and conditional routing
│   │   ├── prompts.py             # System prompt and verdict-output instructions
│   │   └── llm.py                 # Configured LangChain model and structured-output setup
│   ├── tools/
│   │   ├── customer_tools.py      # Customer/KYC profile tool
│   │   ├── account_tools.py       # Account summary and activity-age tool
│   │   ├── transaction_tools.py   # Bounded transactions and deterministic AML signals
│   │   ├── alert_tools.py         # Prior-alert history tool
│   │   └── watchlist_tools.py     # Customer/counterparty watchlist-screening tool
│   ├── audit/
│   │   ├── audit_logger.py        # Writes audit-run and audit-event records
│   │   ├── evidence_builder.py    # Builds and saves a complete evidence package
│   │   └── review.py              # Saves and logs human-review decisions
│   └── static/
│       └── index.html             # One-page analyst demo UI
├── data/
│   └── aml.db                     # Generated SQLite database; not hand edited
├── audit/
│   ├── evidence_logs/             # One evidence JSON file per investigation
│   └── sar_drafts/                # Reserved for future SAR-draft examples; unused initially
├── requirements.txt               # Pinned/minimum Python dependencies
├── .env.example                   # Safe configuration-variable template
└── README.md                      # Setup, architecture, testing, and interview notes
```

`data/aml.db`, `audit/evidence_logs/`, and `audit/sar_drafts/` are runtime artifacts/directories. They will be created by initialization/import code in later phases, not committed as manually authored logic. The project will not create or seed synthetic AML records: the database is populated only from dataset files supplied by the project owner.

## 4. File responsibilities and data flow

`api.py` receives an alert, creates an investigation record, executes the graph, and turns queued audit-safe events into an SSE response. It also hosts alert, audit, evidence, and review endpoints.

`database.py` owns the SQLite path, connection configuration, table creation, and small parameterized query helpers. SQL stays in the data-access/tool layer, never in prompts or model output.

`import_data.py` loads the project owner's supplied CSV and/or Excel files into SQLite using explicit column mappings and parameterized inserts. `validate_dataset.py` checks the imported records before the investigation service uses them. `schema_mapper.py` is used only if source names differ from the investigation concepts; it documents the mapping rather than silently guessing it.

The `tools/` modules are the policy enforcement layer. They accept only narrow inputs, use parameterized SQL, calculate signals in Python, cap returned transactions, and emit evidence-ready JSON. LangChain exposes these functions to the graph; it does not give the LLM general database access.

The `agent/` modules define state, prompt rules, LLM configuration, and the graph loop. They preserve tool messages and produce only compact investigator-facing summaries plus a validated final verdict.

The `audit/` modules create a chronological durable record, write the evidence package, and preserve human approval/rejection separately from the model recommendation.

## 5. Database design approach

The required entities below are the target investigation concepts, not a commitment to force an unknown source dataset into a fixed physical schema. Phase 2A will first inspect the supplied files and create a data dictionary. Phase 2B will then decide whether the source columns can be loaded directly, need a documented mapping, or need normalized derived tables. No records will be invented to fill missing fields.

Where source data supports it, identifiers will be stored as text, dates normalized to ISO-8601 text, and monetary values loaded using a documented precision strategy. Any changes required by the actual files will be explained before implementation.

### `customers`

| Column | Purpose |
| --- | --- |
| `customer_id` | Primary key used by alerts, accounts, and transactions. |
| `name` | Name for customer watchlist screening. |
| `occupation` | Context for expected activity. |
| `declared_annual_income` | Baseline for deterministic income-mismatch checks. |
| `risk_rating` | KYC risk classification. |
| `kyc_status` | Whether KYC is current/complete. |
| `pep_flag` | Politically exposed person indicator. |

### `accounts`

| Column | Purpose |
| --- | --- |
| `account_id` | Primary key. |
| `customer_id` | Customer relationship key. |
| `account_type` | Context such as checking or business account. |
| `balance` | Current balance snapshot. |
| `status` | Account status. |
| `last_activity_date` | Used to compute activity recency. |

### `transactions`

| Column | Purpose |
| --- | --- |
| `transaction_id` | Primary key and evidence reference. |
| `account_id`, `customer_id` | Relationship keys for scoped retrieval. |
| `transaction_date` | Window filtering and rapid-movement ordering. |
| `direction` | `CREDIT` or `DEBIT`. |
| `amount`, `currency` | Monetary evidence. Supported currencies and precision are determined from the provided source data. |
| `counterparty_name`, `counterparty_country` | Watchlist and geographic context. |
| `channel` | For example wire, cash, ACH. |
| `description` | Small contextual detail. |

### `alert_history`

| Column | Purpose |
| --- | --- |
| `alert_id` | Primary key for historical alert. |
| `customer_id`, `alert_date` | Relationship and chronology. |
| `triggered_rules` | Historical rule labels. |
| `previous_verdict` | Prior analyst outcome. |
| `analyst_note` | Legitimate-activity or escalation context. |
| `sar_filed_flag` | Whether a SAR was already filed. |

### `watchlist`

| Column | Purpose |
| --- | --- |
| `watchlist_id` | Primary key. |
| `entity_name`, `aliases` | Exact and alias comparison source. |
| `risk_type`, `country`, `risk_score` | Explainable screening context. |

### `audit_runs`

One row per submitted investigation. It stores `investigation_id`, alert/customer identifiers, start/completion time, lifecycle `status`, final verdict and confidence, plus LLM provider/model metadata.

### `audit_events`

Append-only chronological events: `event_id`, `investigation_id`, `sequence_number`, `event_type`, `timestamp`, and `payload_json`. It preserves safe summaries, inputs, tool results, verdict, and review events without chain-of-thought.

### `human_reviews`

One or more independently stored review records: `review_id`, `investigation_id`, `reviewer`, `decision`, `notes`, and `reviewed_at`. The investigator recommendation is never silently replaced; human review is separately visible in the audit history.

## 6. Controlled investigation tools

All five tools return JSON-serializable, bounded results with a `source`/evidence context. The graph receives them as tool messages and the audit layer stores the same safe output.

1. `get_customer_profile(customer_id)` returns the customer’s KYC status, risk rating, income, occupation, and PEP flag.
2. `get_account_summary(customer_id)` returns the customer’s accounts and computes `days_since_last_activity` from the current date.
3. `get_transaction_history(customer_id, observation_start, observation_end)` filters the alert window and returns a summary plus a limited set of material transactions. Python calculates:
   - `total_credits`, `total_debits`, and `transaction_count`;
   - `retention_ratio = ending retained value / credits` (with zero-credit handling);
   - `structuring_presignal`: multiple credits just below the configured reporting threshold within a short window;
   - `rapid_outflow_detected`: a large debit shortly after inbound credit activity;
   - `income_mismatch`: alert-window inflows materially exceed a defined proportion of declared annual income.
4. `get_prior_alert_history(customer_id)` returns historical alerts, SAR filing status, analyst notes, and false-positive context.
5. `screen_watchlist(customer_id)` checks customer and selected counterparties. It applies exact normalized-name match, aliases split from the `aliases` column, then a simple token-set Jaccard score. It returns match method, match confidence/score, and risk context; it does not claim a fuzzy match is a confirmed sanctions hit.

### AML rule mapping

| Rule | Deterministic basis | How the LLM may use it |
| --- | --- | --- |
| `RULE-01` Structuring/smurfing | Repeated credits under the threshold in a compact observation window. | Explain pattern, transaction IDs, amount distribution, and any benign context. |
| `RULE-02` Rapid movement | Major outflow shortly after inbound funds with low retention. | Explain timing, counterparties, and whether funds appear layered/moved. |
| `RULE-03` Income mismatch | Credit volume materially inconsistent with declared income. | Assess significance alongside customer/occupation and prior-alert facts. |
| `RULE-04` Watchlist/sanctions proximity | Exact, alias, or scored fuzzy customer/counterparty match. | Distinguish confirmed exact/alias hit from proximity requiring escalation. |

Thresholds will be explicit constants in Python and documented in the README. This makes tests repeatable and lets an interviewer see where policy decisions live.

## 7. LangGraph workflow

The investigation graph has a deliberately small state:

```text
messages                 LangChain message history (system/user/tool/assistant)
alert                    Submitted alert payload
customer_id              Customer being investigated
investigation_id         Audit correlation ID
tool_results             Named tool outputs already gathered
audit_event_queue        Safe streamable events waiting for API delivery
final_verdict            Validated structured verdict, once available
```

```text
START
  -> agent_node
       ├─ tool call requested -> tools_node -> agent_node
       └─ final JSON verdict -> END
```

`agent_node` builds the evidence-constrained model request from the system prompt, submitted alert, and prior messages. It emits an `analysis_summary` event containing a concise, user-visible rationale summary, never hidden model reasoning. It either requests one allowed tool or produces final JSON conforming to the verdict schema.

`tools_node` dispatches only a requested allow-listed tool, validates its arguments against the alert/customer scope, records `TOOL_CALLED`, executes it, records `TOOL_RESULT`, appends the bounded result to messages and `tool_results`, then loops to `agent_node`.

The routing function tests for a valid tool call. If no call is present, the final JSON is validated with Pydantic; invalid output is handled as a controlled graph error rather than being accepted as a verdict.

### Prompt contract

The system prompt requires visible, concise checkpoints:

- before the first tool: `INITIAL HYPOTHESIS` and `NEXT STEP`;
- after each tool result: `ANALYSIS SUMMARY`, `UPDATED HYPOTHESIS`, and `NEXT STEP`;
- final answer: the exact JSON verdict contract requested for this project.

It also prohibits inventing evidence, instructs the model to cite only tool-returned IDs/data, requires consideration of false-positive factors, and distinguishes watchlist proximity from a confirmed list match. The actual events will be structured payloads rather than exposing raw reasoning text.

## 8. SSE streaming design

`POST /investigate` accepts a compact alert object with an alert ID, customer ID, alert date/window, and triggered-rule context. FastAPI returns `text/event-stream` using an async generator.

The API creates the audit run first, then passes a queue/callback into the graph execution. Each durable, safe event is both logged and yielded in SSE form:

```text
event: tool_call
data: {"investigation_id":"...", "tool":"get_transaction_history", "arguments":{...}}

```

Expected event order:

1. `investigation_started`
2. `system_prompt_built`
3. zero or more `tool_call`, `tool_result`, and `analysis_summary` events
4. `verdict`
5. `audit_saved`

SSE is appropriate because the browser only needs one-way progress updates. The frontend will create a `fetch` request for the POST endpoint and parse its streamed body (native `EventSource` is GET-only). A production system would add client-disconnect handling, authentication, persistence/retry policies, and a job queue; this learning version keeps execution in-process and small.

## 9. Audit trail and evidence package

At investigation start, the API generates a UUID `investigation_id` and inserts a `RUN_STARTED` record in `audit_runs`. Every important action receives an increasing sequence number in `audit_events`.

The investigation lifecycle is:

```text
alert received
  -> audit_runs created
  -> safe events appended to audit_events
  -> graph completes / fails
  -> audit_runs finalized
  -> evidence package written atomically to audit/evidence_logs/{investigation_id}.json
  -> optional human review row + review audit event
```

The evidence JSON contains the original alert, each tool output actually used, validated final verdict, rule-mapped key evidence, false-positive factors considered, and chronological audit events. It will include LLM provider/model metadata but not API keys or private chain-of-thought.

Human review is intentionally post-investigation. Approval/rejection creates a `human_reviews` record and emits `HUMAN_REVIEW_APPROVED` or `HUMAN_REVIEW_REJECTED`; it provides governance without rewriting the automated recommendation.

## 10. Dataset ownership and source-data expectations

The project owner will provide the dataset files. The application will be designed around their real columns and relationships; it will not manufacture customers, transactions, alerts, or watchlist entries.

At Phase 2A, provide the files in the workspace (CSV and/or Excel are supported) and, if available, a short note describing their origin. The implementation will then inspect them and document:

- every source file/sheet and its columns;
- likely primary keys, foreign keys, and relationship cardinalities;
- columns usable for customer profile, account, transaction, alert-history, and watchlist evidence;
- columns required by each AML rule and any unsupported rule because data is absent;
- missing, ambiguous, weak-quality, or sensitive columns; and
- an explicit source-to-SQLite mapping in a data dictionary.

If a required investigation concept is missing (for example, transaction direction, an alert window, or a counterparty name), the limitation will be surfaced in validation and the relevant tool/rule will return an evidence limitation rather than fabricated output. Tiny structural placeholders may be created only if necessary to test package imports; they are never treated as an AML dataset or a completed implementation.

## 11. Implementation phases, deliverables, and tests

### Phase 0 — Plan and architecture (current)

Deliverable: this `implementation.md` only.

Test command (PowerShell):

```powershell
Get-Content .\mini-sar-investigator\implementation.md
```

Expected result: the complete plan rendered as text, with no `app/`, database, or runnable application files yet.

Interview question this prepares: “How would you design an auditable agentic AML investigation system while preventing unrestricted data access?”

### Phase 1 — Project setup

Create the required directories, `requirements.txt`, `.env.example`, and Python package markers if needed for imports. No business logic yet.

Test command: `Get-ChildItem -Recurse .\mini-sar-investigator`

Expected result: the target skeleton matches the requested architecture, and configuration contains placeholders only.

Interview question: “How do you set up a small service so configuration and runtime artifacts are separated from code?”

### Phase 2A — Dataset understanding and data dictionary

This phase starts only after the project owner supplies the dataset files. Inspect each file/sheet and its columns, identify primary keys and relationships, determine which AML concepts/rules the available data can support, identify missing or weak columns, and write a clear data dictionary.

Test command: a documented inspection command run against the provided dataset directory.

Expected result: a readable data dictionary showing source files, columns, data types, key relationships, AML uses, and known data-quality limitations. No SQLite import occurs until this output is reviewed.

Interview question: “How did you assess source-data fitness and avoid building AML logic on assumptions?”

### Phase 2B — SQLite schema design from the provided dataset

Design `database.py` and the SQLite schema from the Phase 2A data dictionary. Prefer the actual source columns and documented mappings over a pre-decided schema. The requested customer, account, transaction, alert-history, watchlist, audit-run, audit-event, and human-review concepts remain the target architecture, but their final table/column layout will match the source data where it differs.

Test command: a documented schema-initialization and schema-inspection command.

Expected result: the generated schema and relationship explanation align with the approved data dictionary; no AML business rows are created by the schema step.

Interview question: “How did you adapt a relational model to heterogeneous source data without losing investigation traceability?”

### Phase 2C — Dataset import pipeline

Create `import_data.py`, `validate_dataset.py`, and `schema_mapper.py` only if mapping is necessary. The importer will load the supplied CSV/Excel files using parameterized SQL, transaction handling, and clear errors. The validator will report row counts, missing values, duplicate identifiers, invalid dates, and foreign-key consistency, plus any rule-critical data gaps.

Test commands: `python -m app.import_data` followed by `python -m app.validate_dataset` (run from `mini-sar-investigator`, with the dataset path supplied through the documented configuration).

Expected result: a SQLite database sourced solely from the provided files, followed by concise per-table validation summaries and a non-zero/clear failure for serious integrity errors.

Interview question: “How did you make a manual, multi-source AML dataset reproducible and safe to load?”

### Phase 3 — Database helpers and controlled tools

Implement five narrow LangChain-compatible tools. Use parameterized queries, bounded transaction selection, and deterministic signal calculations. Add a small direct tool smoke-test entry point or documented Python command.

Test command: a documented Python module command that prints summaries for selected customer IDs from the imported dataset.

Expected result: evidence-ready JSON with no arbitrary SQL path, limited selected transactions, and clear rule pre-signals.

Interview question: “How do you give an LLM access to financial evidence without allowing it to query a production database?”

### Phase 4 — Audit logging and evidence building

Create the audit-run/event helpers and evidence builder. Verify chronological sequence numbers and a complete evidence file using an alert from the imported dataset.

Test command: documented audit smoke test followed by `Get-Content .\audit\evidence_logs\<investigation_id>.json`.

Expected result: database audit rows and an evidence JSON that agree on the same event order.

Interview question: “What would an auditor be able to reconstruct after an automated recommendation?”

### Phase 5 — LangChain and LangGraph agent

Create typed graph state, prompt, LLM setup, allow-listed dispatch, conditional routing, verdict validation, and graph smoke test. Model configuration stays in environment variables. We will include a clear behavior when an API key/provider is unavailable rather than hiding the dependency.

Test command: documented graph test after setting `LLM_PROVIDER=groq`,
`GROQ_API_KEY`, and a `GROQ_MODEL` available in the user's Groq account.

Expected result: a sequence of controlled tool calls ending in schema-valid JSON; the model cannot request arbitrary database operations.

Interview question: “Why use LangGraph instead of a single LLM call, and how do you stop the loop safely?”

### Phase 6 — FastAPI investigation endpoint and SSE

Implement `POST /investigate` and `GET /alerts`, where the latter returns available alerts from the imported dataset. Connect graph events to durable audit records and SSE output.

Test command: `uvicorn app.api:app --reload`, then a documented `curl.exe` or PowerShell request to `/investigate`.

Expected result: ordered `investigation_started`, tool, summary, verdict, and `audit_saved` events in `text/event-stream` format.

Interview question: “How did you deliver a real-time investigator experience without exposing model reasoning?”

### Phase 7 — Audit retrieval and human review endpoints

Add audit run list/detail/evidence routes plus the review endpoint. Validate review decisions and log approval/rejection events.

Test command: documented GET/POST calls using an investigation ID produced in Phase 6.

Expected result: run history, audit events, evidence content, and an independently stored human-review decision.

Interview question: “Where is the human-in-the-loop control and how is it made auditable?”

### Phase 8 — Minimal frontend

Create one static HTML page to select an imported alert (or enter a supported alert payload), start an investigation, render structured SSE events, and display the final verdict.

Test command: run the FastAPI server and open `http://127.0.0.1:8000/`.

Expected result: a small working analyst console; it is intentionally not a production UI.

Interview question: “How would an investigator observe an agent’s progress safely and decide whether to review it?”

### Phase 9 — README and interview notes

Write complete setup instructions, text architecture diagram, schema/tool/workflow/audit explanations, responsible-AI controls, troubleshooting, and a UBS-oriented interview narrative.

Test command: `Get-Content .\README.md`.

Expected result: a new developer can run the demo and explain its trade-offs without reading the source first.

Interview question: “Walk me through your AML SAR Investigator project end to end.”

## 12. Acceptance criteria for the finished project

- Alerts and customers from the supplied dataset lead to explainable, evidence-backed outcomes within the limits documented in the data dictionary.
- The graph can call only the five controlled Python tools.
- Deterministic signals originate in Python, not model arithmetic or judgment alone.
- Final verdicts validate against the required JSON contract.
- Every streamed operational event is persisted with order and timestamp.
- Every completed investigation produces a recoverable evidence package.
- A human review is independent, stored, and auditable.
- The README explains security/responsible-AI controls and the technical architecture in interview-ready language.
