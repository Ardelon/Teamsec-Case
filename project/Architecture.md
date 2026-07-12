# System Design Map

## Overview

Teamsec is a multi-tenant ETL financial data platform that ingests loan data from an external bank API, processes it through a native Rust pipeline, and persists results in a PostgreSQL warehouse. A Django gateway exposes REST endpoints, JWT authentication, and an HTMX web UI. Background processing is handled by Celery workers that embed the compiled `adapter_core` PyO3 module.

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
│  │  Django REST Framework · JWT Auth · HTMX Dashboard         │   │
│  └──────────────────────────┬───────────────────────────────┘   │
│                             │ Celery enqueue                     │
│                             ▼                                    │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              background_worker                            │   │
│  │  Celery daemon · adapter_core (Rust/PyO3 via Maturin)  │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

### external_bank/
Isolated Django application simulating a third-party bank API. Serves tenant-scoped loan feeds at `/api/v1/loans/<tenant_id>/`. Runs independently on port 8080 with its own SQLite store.

### api/
Django gateway handling:
- REST routes (`/api/health/`, `/api/auth/token/`)
- ETL job orchestration (`/etl/jobs/`)
- HTMX dashboard for interactive job triggering
- PostgreSQL persistence for `ETLJob` records
- Celery task dispatch to `background_worker`

### adapter/
Rust core compiled as a `cdylib` via Maturin/PyO3. Exposes `execute_etl_pipeline(job_id, tenant_id, loan_type)` to Python. Future iterations will fetch bank data via `reqwest`, parse CSV streams, and apply `rust_decimal` transformations.

### background_worker
Headless Celery worker container. Builds and installs `adapter_core` at image build time, then processes `run_etl_pipeline` tasks asynchronously.

## Data Flow

1. User triggers ETL via HTMX dashboard or REST `POST /etl/jobs/trigger/`.
2. `core_backend_api` enqueues a Celery task on `redis_broker`.
3. `background_worker` picks up the task, calls `adapter_core.execute_etl_pipeline()`.
4. Rust adapter processes the job (currently returns initialization confirmation; full pipeline TBD).
5. Job status and result are written back to `postgres_warehouse` via Django ORM.

## Multi-Tenancy Model

Tenants are identified by `tenant_id` strings propagated through JWT claims, ETL job records, and bank API paths. Each tenant's loan data is isolated at the API contract level.

## Technology Stack

| Layer            | Technology                          |
|------------------|-------------------------------------|
| API Gateway      | Django 5+, DRF, HTMX                |
| Auth             | PyJWT                               |
| Task Queue       | Celery + Redis 7                    |
| Data Warehouse   | PostgreSQL 15                       |
| ETL Engine       | Rust (PyO3 0.20, Maturin)           |
| Orchestration    | Docker Compose                      |
