# 📧 Email Automation Agent — Apache Airflow + Microsoft Graph + OpenAI

An intelligent, production-ready email automation system that reads incoming emails from Microsoft Outlook (via Microsoft Graph API), classifies their intent using OpenAI, auto-replies when data is found in Google Sheets, and forwards unresolvable emails to a human agent — all orchestrated by Apache Airflow and monitored through a Streamlit/Plotly dashboard backed by PostgreSQL.

---

## 📑 Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Key Features](#key-features)
- [Project Structure](#project-structure)
- [How It Works](#how-it-works)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Environment Variables](#environment-variables)
- [Setup & Installation](#setup--installation)
- [Running with Docker](#running-with-docker)
- [Apache Airflow DAG](#apache-airflow-dag)
- [API Reference](#api-reference)
- [Database Schema](#database-schema)
- [Dashboard](#dashboard)
- [Configuration](#configuration)
- [Security Notes](#security-notes)
- [Contributing](#contributing)

---

## Overview

This project automates the handling of incoming business emails end-to-end. It is designed primarily for logistics and supply-chain support workflows (e.g., **Track & Trace** and **Vessel Schedule** queries), though it is fully configurable for any domain.

The agent:
1. Polls a Microsoft 365 mailbox via Microsoft Graph API.
2. Classifies each email's domain/intent using OpenAI.
3. Extracts entity IDs (e.g., container numbers, booking IDs) from the email body.
4. Looks up those IDs in a Google Sheet to find relevant data.
5. Auto-generates and sends a reply using OpenAI if data is found.
6. Forwards emails it cannot handle to a human agent.
7. Persists all email metadata into PostgreSQL via an Apache Airflow ETL DAG.
8. Computes response-time metrics per email thread.
9. Exposes a live dashboard (Streamlit + Plotly) for monitoring.

---

## Architecture

```
Microsoft 365 Mailbox
        │
        ▼
Microsoft Graph API  ──►  ms_graph_auth.py / ms_graph_client.py
        │
        ▼
FastAPI App  (main.py)
  ├── classify_query_domain()        ← OpenAI (ai_agent.py)
  ├── extract_entity_with_openai()   ← OpenAI (ai_agent.py)
  ├── search_sheet_for_entity()      ← Google Sheets (google_sheets.py)
  ├── generate_reply_with_openai()   ← OpenAI (ai_agent.py)
  └── send/forward via Graph API     ← ms_graph_client.py

Apache Airflow DAG  (incoming_with_response_table_with_timezone.py)
  ├── get_graph_token()              ← OAuth2 client credentials
  ├── extract_emails_from_folders()  ← Graph API pagination
  ├── load_to_postgres()             ← email_group table
  └── compute_response_metrics()     ← email_response table

Airflow Trigger API  (airflow_trigger.py)
  └── POST /aqua/trigger-etl         ← triggers DAG run via Airflow REST API

Dashboard
  ├── streamlit_dashboard.py         ← Streamlit UI
  ├── app_plotly.py                  ← Plotly charts
  └── db_utils.py                    ← PostgreSQL queries

Docker Compose
  ├── postgres (port 5432)
  └── streamlit (port 8501)
```

---

## Key Features

- **Automated email triage** — classifies and routes emails without human intervention.
- **OpenAI-powered NLU** — entity extraction and reply generation using GPT.
- **Google Sheets as a live data source** — no need for a separate database for reference data.
- **Apache Airflow ETL pipeline** — scheduled daily ingestion of emails into PostgreSQL with full pagination support across mailbox folders.
- **Response-time analytics** — computes per-thread reply latency and stores it in `email_response`.
- **Timezone-aware timestamps** — all datetime fields are stored with timezone information (`TIMESTAMP WITH TIME ZONE`).
- **Human escalation path** — emails outside supported domains or with unresolvable IDs are automatically forwarded to a configurable human agent.
- **REST API for runtime configuration** — update watched mailbox, forwarding address, and allowed domains at runtime without restarting the service.
- **Dashboard** — live Streamlit UI backed by PostgreSQL for operational visibility.
- **Dockerized deployment** — PostgreSQL and Streamlit run as Docker services with environment-variable-driven configuration.

---

## Project Structure

```
Email_Automation_Agent-Apache-Airflow/
│
├── main.py                                        # FastAPI app — core email processing logic
├── ai_agent.py                                    # OpenAI wrappers: classify, extract, generate
├── ms_graph_auth.py                               # Microsoft Graph OAuth2 token acquisition
├── ms_graph_client.py                             # Graph API: fetch, send, mark-as-read
├── google_sheets.py                               # Google Sheets lookup via gspread
├── config.py                                      # Env-var config loader
│
├── incoming_with_response_table_with_timezone.py  # Airflow DAG: ETL + response metrics
├── airflow_trigger.py                             # FastAPI router: trigger Airflow DAG via REST
│
├── db_utils.py                                    # PostgreSQL query helpers (psycopg2 + pandas)
├── streamlit_dashboard.py                         # Streamlit monitoring dashboard
├── app_plotly.py                                  # Plotly chart components
│
├── docker-compose.yml                             # Docker: PostgreSQL + Streamlit services
├── requirements.txt                               # Python dependencies
├── .env                                           # Environment variables (do not commit)
└── README.md
```

---

## How It Works

### Email Processing Flow (`main.py`)

When `POST /process-emails` is called, the system:

1. **Fetches unread emails** from the configured Microsoft 365 mailbox via the Graph API.
2. **Classifies** each email's domain using OpenAI (e.g., `"Track and Trace"`, `"Vessel Schedule"`, or something else).
3. **Checks** if the domain is in the `allowed_domains` list (configurable at runtime).
   - If **not allowed**: email is forwarded to the human agent and marked as read.
   - If **allowed**: proceed to step 4.
4. **Extracts an entity ID** (e.g., a container number or booking reference) from the email body using OpenAI.
5. **Looks up** the entity ID in Google Sheets.
   - If **found**: generates a reply using OpenAI with the row data and sends it back to the sender.
   - If **not found**: forwards the email to the human agent.
6. **Marks the email as read** in all cases to prevent reprocessing.
7. **Updates in-memory stats** (`automated` vs `forwarded` counts and per-domain breakdown).

### Airflow ETL DAG (`incoming_with_response_table_with_timezone.py`)

The DAG `ms_graph_email_etl_postgres` runs on a `@daily` schedule with four tasks chained in sequence:

| Task | What it does |
|---|---|
| `get_graph_token` | Acquires an OAuth2 bearer token using client credentials (tenant ID, client ID, secret). |
| `extract_emails_from_folders` | Reads folder names from Airflow Variables (`MS_GRAPH_FOLDER_NAMES`), resolves folder IDs, and paginates through all emails in each folder. |
| `load_to_postgres` | Creates the `email_group` table if it doesn't exist and upserts all fetched emails (conflict on `email_id`). |
| `compute_response_metrics` | Groups emails by `thread_id`, computes reply latency in seconds for each thread, and upserts results into `email_response`. |

### Airflow Trigger API (`airflow_trigger.py`)

A `POST /aqua/trigger-etl` endpoint allows external callers to trigger the ETL DAG on demand. It:
- Looks up the user's monitored folder from the database.
- Uses the Airflow REST API (`DAGRunApi`) to submit a new DAG run with a unique `run_id` and passes `user_email` + `folder_names` as DAG configuration.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Email source | Microsoft Graph API (OAuth2, client credentials) |
| AI / NLU | OpenAI GPT (entity extraction, classification, reply generation) |
| Reference data | Google Sheets via `gspread` |
| Orchestration | Apache Airflow (TaskFlow API, `@daily` schedule) |
| Backend API | FastAPI |
| Database | PostgreSQL 13 (via `psycopg2`, Airflow `PostgresHook`) |
| Dashboard | Streamlit + Plotly |
| Configuration | `.env` + `python-dotenv` |
| Containerisation | Docker Compose |
| Language | Python 3.x |

---

## Prerequisites

- Python 3.9+
- Docker & Docker Compose
- An **Azure App Registration** with the following Microsoft Graph API permissions (application-level):
  - `Mail.Read`
  - `Mail.Send`
  - `Mail.ReadWrite`
- An **OpenAI API key**
- A **Google Cloud service account** JSON key with access to the target Google Sheet
- A running **Apache Airflow** instance (2.x recommended) with:
  - A PostgreSQL connection registered as `postgres_default`
  - Airflow Variables set: `MS_GRAPH_USER_EMAIL`, `MS_GRAPH_FOLDER_NAMES`

---

## Environment Variables

Create a `.env` file in the project root (never commit this file):

```env
# Microsoft Graph / Azure
MS_GRAPH_TENANT_ID=your-azure-tenant-id
MS_GRAPH_CLIENT_ID=your-azure-client-id
MS_GRAPH_CLIENT_SECRET=your-azure-client-secret

# OpenAI
OPENAI_API_KEY=sk-...

# Google Sheets
GOOGLE_SHEET_ID=your-google-sheet-id

# Human escalation
HUMAN_AGENT_EMAIL=support-human@yourcompany.com

# PostgreSQL (for Streamlit dashboard)
DB_NAME=postgres_db
DB_USER=postgres_user
DB_PASSWORD=postgres_password
DB_HOST=localhost
DB_PORT=5432
```

> **Note:** For the Airflow DAG, `MS_GRAPH_TENANT_ID`, `MS_GRAPH_CLIENT_ID`, and `MS_GRAPH_CLIENT_SECRET` must be available as environment variables in the Airflow worker environment. `MS_GRAPH_USER_EMAIL` and `MS_GRAPH_FOLDER_NAMES` are read from Airflow Variables.

---

## Setup & Installation

### 1. Clone the repository

```bash
git clone https://github.com/rishabhvenkat/Email_Automation_Agent-Apache-Airflow.git
cd Email_Automation_Agent-Apache-Airflow
```

### 2. Create and activate a virtual environment

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Set up environment variables

```bash
cp .env.example .env
# Edit .env and fill in all required values
```

### 5. Add Google Sheets credentials

Place your Google Cloud service account JSON file in the project root and name it:

```
google_creds.json
```

### 6. Run the FastAPI app

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 7. Deploy the Airflow DAG

Copy `incoming_with_response_table_with_timezone.py` to your Airflow `dags/` directory. Airflow will auto-discover it on the next scheduler cycle.

---

## Running with Docker

The `docker-compose.yml` starts two services: PostgreSQL and the Streamlit dashboard.

```bash
# Build and start services
docker-compose up --build

# Run in background
docker-compose up -d

# Stop all services
docker-compose down
```

| Service | Port | Description |
|---|---|---|
| `postgres` | `5432` | PostgreSQL 13 database |
| `streamlit` | `8501` | Streamlit monitoring dashboard |

The Streamlit container mounts the project directory and passes all `DB_*` environment variables from your `.env` file.

---

## Apache Airflow DAG

**DAG ID:** `ms_graph_email_etl_postgres`

**Schedule:** `@daily`

**Tags:** `email`, `graph`, `etl`, `postgres`

**Task graph:**

```
get_graph_token  →  extract_emails_from_folders  →  load_to_postgres  →  compute_response_metrics
```

### Airflow Variables required

Set these in the Airflow UI under **Admin → Variables**:

| Variable | Example Value | Description |
|---|---|---|
| `MS_GRAPH_USER_EMAIL` | `mailbox@company.com` | The mailbox to read emails from |
| `MS_GRAPH_FOLDER_NAMES` | `["Inbox", "Support"]` | JSON array of folder names to process |

### Triggering the DAG via API

```bash
curl -X POST http://localhost:8000/aqua/trigger-etl \
  -H "Content-Type: application/json" \
  -d '{"data": {"email_id": "mailbox@company.com"}}'
```

---

## API Reference

All endpoints are served by the FastAPI app (`main.py`).

### `POST /process-emails`

Triggers background email processing.

**Response:**
```json
{ "status": "processing" }
```

### `POST /config`

Updates runtime configuration (listened mailbox, forwarding address, allowed domains).

**Request body:**
```json
{
  "listen": "monitored@company.com",
  "forward": "human@company.com",
  "allowed_domains": ["Track and Trace", "Vessel Schedule"]
}
```

**Response:**
```json
{ "status": "success" }
```

### `GET /dashboard`

Returns current automation statistics.

**Response:**
```json
{
  "totals": { "automated": 42, "forwarded": 8 },
  "query_breakdown": {
    "Track and Trace": 35,
    "Vessel Schedule": 7,
    "Other": 8
  },
  "allowed_domains": ["Track and Trace", "Vessel Schedule"]
}
```

### `POST /aqua/trigger-etl`

Triggers the Airflow ETL DAG for a given user mailbox.

**Request body:**
```json
{
  "data": { "email_id": "user@company.com" }
}
```

**Response:**
```json
{
  "status": "success",
  "message": "ETL triggered",
  "data": { "run_id": "etl_run_a1b2c3d4" },
  "error": null
}
```

---

## Database Schema

### `email_group`

Stores all fetched emails, one row per message.

| Column | Type | Description |
|---|---|---|
| `email_id` | `TEXT PRIMARY KEY` | Unique Graph API message ID |
| `thread_id` | `TEXT` | Conversation/thread ID for grouping |
| `from_name` | `TEXT` | Display name of the sender |
| `from_email` | `TEXT` | Email address of the sender |
| `subject` | `TEXT` | Email subject line |
| `received_date` | `DATE` | Date portion of received timestamp |
| `received_time` | `TIME` | Time portion of received timestamp |
| `full_received_datetime` | `TIMESTAMP WITH TIME ZONE` | Full timezone-aware received timestamp |
| `folder` | `TEXT` | Source mailbox folder name |

### `email_response`

Stores per-thread response time metrics, computed by the Airflow DAG.

| Column | Type | Description |
|---|---|---|
| `thread_id` | `TEXT PRIMARY KEY` | Conversation thread ID |
| `from_email` | `TEXT` | Original sender email |
| `folder` | `TEXT` | Source folder |
| `response_time_seconds` | `FLOAT` | Seconds between first message and first reply in the thread |

---

## Dashboard

The Streamlit dashboard (port `8501`) provides:

- **Folder-level filtering** — select a specific inbox folder to inspect.
- **Email group table** — full view of ingested emails from `email_group`.
- **Response metrics table** — per-thread response times from `email_response`.
- **Plotly charts** (`app_plotly.py`) — visual analytics over email volume and response performance.

Access the dashboard at: `http://localhost:8501`

---

## Configuration

The `config_store` dict in `main.py` holds the runtime configuration and can be updated live via the `/config` endpoint without restarting the service:

```python
config_store = {
    "listen": "",                              # Mailbox to watch (optional filter)
    "forward": HUMAN_AGENT_EMAIL,              # Fallback forwarding address
    "allowed_domains": [                       # Domains the agent will auto-handle
        "Track and Trace",
        "Vessel Schedule"
    ]
}
```

---

## Security Notes

- **Never commit `.env` or `google_creds.json`** — both files contain sensitive credentials. Add them to `.gitignore`.
- The `.env` file is already present in the repository — review and rotate any credentials that may have been accidentally committed.
- The Microsoft Graph integration uses **app-only (client credentials)** authentication. Ensure the Azure App Registration follows the principle of least privilege.
- The `airflow_trigger.py` router has no authentication middleware in the current implementation. In production, protect this endpoint with API key validation or OAuth2.
- SQL queries in `db_utils.py` use f-string interpolation for the folder filter — consider switching to parameterised queries to prevent SQL injection.

---

## Contributing

1. Fork the repository.
2. Create a feature branch: `git checkout -b feature/your-feature-name`
3. Commit your changes with clear messages.
4. Push and open a Pull Request against `main`.

Please ensure any new environment variables are documented in the [Environment Variables](#environment-variables) section and that secrets are never hardcoded.

---

## License

This project is currently unlicensed. Please contact the repository owner before using this in production or redistributing it.
