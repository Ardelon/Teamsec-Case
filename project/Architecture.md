# System Design Map

## Overview

Teamsec is a multi-tenant ETL financial data platform that ingests loan data from an external bank API, processes it through a native Rust pipeline, and persists results in a PostgreSQL warehouse. A Django gateway exposes REST endpoints, session-based operator authentication (optional Bearer JWT for tooling), and an HTMX web UI. Background processing is handled by Celery workers that embed the compiled `adapter_core` PyO3 module.

## Runtime Topology

```
┌─────────────────────────────────────────────────────────────────────┐
│                        teamsec_network (bridge)                     │
│                                                                     │
│  ┌──────────────┐   ┌──────────────┐   ┌────────────────────────┐ │
│  │ postgres_    │   │ redis_       │   │ external_bank_sim :8080│ │
│  │ warehouse    │   │ broker       │   │ (fake bank REST API)   │ │
│  │ :5432        │   │ :6379        │   └───────────┬────────────┘ │
│  └──────┬───────┘   └──────┬───────┘               │              │
│         │                  │                        │ HTTP         │
│         │                  │                        ▼              │
│  ┌──────┴──────────────────┴──────────────────────────────────┐   │
│  │              core_backend_api :8000                        │   │
│  │  Django REST Framework · Session Auth · HTMX Dashboard     │   │
│  └──────────────────────────┬─────────────────────────────────┘   │
│                             │ Celery enqueue                     │
│                             ▼                                    │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              background_worker                            │   │
│  │  Celery daemon · adapter_core (Rust/PyO3 via Maturin)     │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

### external_bank/
Isolated Django application simulating a third-party bank. Stores CSV portfolios on disk and streams JSON arrays at `/api/bank/export/credits` and `/api/bank/export/payments`. Runs on port 8080 with SQLite metadata. Unauthenticated by design for local demos.

### api/
Django gateway handling:
- Auth and health (`/api/auth/login`, `/api/auth/logout`, `/api/auth/session`, `/api/health/`)
- Sync orchestration (`/api/sync`, status, cancel, active)
- Warehouse snapshot and profiling (`/api/data`, `/api/profiling`)
- HTMX dashboard (`/login/`, `/dashboard/`)
- Redis distributed lock per `tenant_id` + `loan_type`
- Celery task dispatch to `background_worker`

### adapter/
Rust core compiled as a `cdylib` via Maturin/PyO3. Exposes `execute_etl_pipeline(...)` to Python. Streams bank JSON over HTTP (`reqwest`), validates rows (`rust_decimal` / date parsers), and batch-writes into Postgres inside a single snapshot transaction (delete tenant+loan_type slice, then insert). Tokio work runs with the GIL released; progress callbacks re-acquire the GIL briefly.

### background_worker
Headless Celery worker container. Builds and installs `adapter_core` at image build time, then processes `run_etl_pipeline` tasks asynchronously.

## Data Flow

1. Operator authenticates via `POST /api/auth/login` (HttpOnly session cookie) and triggers sync via HTMX dashboard or `POST /api/sync`.
2. `core_backend_api` acquires a Redis lock (`lock:{tenant}:{loan_type}`, TTL 14400s), creates an `ETLJob`, and enqueues Celery.
3. `background_worker` calls `adapter_core.execute_etl_pipeline()` with bank export URLs and the warehouse DB URL.
4. Rust adapter streams credits then payments, validates rows, and commits a tenant snapshot to `postgres_warehouse`.
5. Progress updates the Django job record; the lock is released when the Celery task exits (`finally`). Cancel sets a Redis flag and soft-revokes the task; the Python progress callback returns `false` so Rust aborts before commit (open snapshot txn rolls back). For **PROCESSING** jobs the lock stays held until that worker finishes so a new sync cannot write the same slice concurrently. **QUEUED** cancels release the lock immediately (no writer started).
6. Dashboard hydrates via `GET /api/data` and `GET /api/profiling` — post-ingest Django aggregates over the warehouse (not streaming profiler stats inside Rust).

### Sync process

Six-phase sync matching the as-built system (session-first HTMX UI, Celery + Postgres job state, dual bank exports, Django-side profiling).

```mermaid
sequenceDiagram
  autonumber
  actor User as Bank Administrator
  participant UI as TeamSec HTMX Dashboard
  participant API as Core Backend REST API
  participant Redis as Redis Broker and Lock
  participant Worker as Background Worker
  participant Rust as Adapter Core Rust
  participant Bank as External Bank Sim
  participant DB as PostgreSQL Warehouse

  Note over User,API: Phase 1 Authorization and session
  User->>UI: Enter credentials and select tenant
  UI->>API: POST /api/auth/login
  API-->>UI: HttpOnly session cookie plus optional JWT for tooling
  Note over UI: UI uses session cookie only not localStorage JWT

  Note over User,API: Phase 2 Sync trigger and client guardrail
  User->>UI: Click Sync Data for loan_type
  alt sync button already disabled
    Note over UI: Drop click spinner stays active
  else ready to sync
    Note over UI: Disable Sync enable Cancel show spinner
    UI->>API: POST /api/sync loan_type with session cookie
  end

  Note over API,Redis: Phase 3 Distributed lock and Celery enqueue
  Note over API: Tenant from session or Bearer claims
  API->>Redis: SET NX lock tenant loan_type TTL 14400s
  alt lock already held
    Redis-->>API: Lock denied
    API-->>UI: HTTP 409 active job payload
  else lock acquired
    Redis-->>API: Lock granted
    API->>DB: Insert ETLJob QUEUED
    API->>Redis: Celery enqueue run_etl_pipeline
    API-->>UI: HTTP 202 job_id
  end

  Note over UI,API: Phase 4 Progress polling
  loop Every 3s HTMX hx-trigger
    UI->>API: GET sync status partial or /api/sync/status/job_id
    API->>DB: Load ETLJob progress status errors
    API-->>UI: Status payload QUEUED PROCESSING COMPLETED FAILED CANCELLED
  end

  Note over Redis,DB: Phase 5 Async ingest validate snapshot
  Worker->>Redis: Claim Celery task
  Worker->>DB: Mark ETLJob PROCESSING
  Worker->>Rust: execute_etl_pipeline via PyO3
  Rust->>Bank: Stream GET export/credits then export/payments
  Bank-->>Rust: Chunked JSON streams
  Note over Rust: Parse validate normalize fail-closed skips soft-null bad fields
  Rust->>DB: BEGIN snapshot txn
  Rust->>DB: DELETE slice tenant loan_type then bulk INSERT
  Rust-->>Worker: Progress callback every 2k rows
  Worker->>DB: Update processed_rows progress_percentage
  alt pipeline succeeded
    Rust->>DB: COMMIT snapshot
    Rust-->>Worker: Success metrics and validation errors
    Worker->>DB: ETLJob COMPLETED
  else hard failure or cancel abort
    Note over Rust,DB: Drop writer open txn rolls back old slice intact
    Rust-->>Worker: Failure or cancelled
    Worker->>DB: ETLJob FAILED or leave CANCELLED
  end
  Worker->>Redis: Release lock in finally clear cancel flags

  Note over UI,DB: Phase 6 Dashboard hydration
  Note over UI: Polling sees terminal status
  UI->>API: GET /api/data and /api/profiling
  API->>DB: Tenant-scoped warehouse reads
  DB-->>API: Rows and aggregate profiling stats
  API-->>UI: Presentation JSON
  Note over UI: Re-enable Sync hydrate tables charts
```

### Cancel process

Cooperative abort path added beyond the baseline sync design.

```mermaid
flowchart TD
  startCancel[POST /api/sync/cancel/job_id] --> markFlag[Set Redis job cancel flag]
  markFlag --> softRevoke[Celery revoke terminate false]
  softRevoke --> markJob[ETLJob status CANCELLED]
  markJob --> branch{Was status QUEUED?}
  branch -->|yes| releaseNow[Release Redis slice lock now]
  branch -->|no PROCESSING| holdLock[Keep lock until worker exits]
  holdLock --> callback[Progress callback returns false]
  callback --> abortRust[Rust aborts before COMMIT]
  abortRust --> rollback[Open snapshot txn rolls back]
  rollback --> finallyRelease[Worker finally releases lock]
  releaseNow --> done[Slice free for new sync]
  finallyRelease --> done
```

## Validation Policy

Missing `loan_account_number` (credits) or payments referencing unknown accounts are **fail-closed** — the row is skipped and logged. Invalid dates/numerics on otherwise accepted rows are **soft**: the bad field is stored as null, the row is still written, and an error is appended to the job log. Prefer clean bank exports for a clean warehouse.

## Multi-Tenancy Model

Tenants are fixed demo IDs (`BANK001`, `BANK002`, `BANK003`) propagated through session/JWT claims, ETL job records, bank storage paths, and warehouse rows. Loan types are `RETAIL` and `COMMERCIAL`. Concurrent syncs for the same tenant are allowed across loan types; the same tenant+loan_type pair is serialized by the Redis lock.

## Technology Stack

| Layer            | Technology                          |
|------------------|-------------------------------------|
| API Gateway      | Django 5+, DRF, HTMX                |
| Auth             | Django session cookie (+ optional Bearer JWT for tooling) |
| Task Queue       | Celery + Redis 7                    |
| Data Warehouse   | PostgreSQL 15                       |
| ETL Engine       | Rust (PyO3, Maturin)                |
| Orchestration    | Docker Compose                      |
