# Teamsec Multi-Tenant ETL Financial Data Platform

Containerized Python/Django gateway with a Rust-native ETL adapter, fake external bank simulator, PostgreSQL warehouse, and Redis-backed Celery workers.

## Architecture

| Service              | Port | Role                                      |
|----------------------|------|-------------------------------------------|
| postgres_warehouse   | 5432 | PostgreSQL 15 data warehouse              |
| redis_broker         | 6379 | Celery broker and distributed lock manager|
| external_bank_sim    | 8080 | Isolated fake bank API                    |
| core_backend_api     | 8000 | Django REST + HTMX gateway                |
| background_worker    | —    | Celery worker with Rust `adapter_core`    |

All services communicate over the internal `teamsec_network` Docker bridge.

## Quick Start

```bash
docker compose up --build
```

- Login UI: http://localhost:8000/login/
- Dashboard: http://localhost:8000/dashboard/
- Bank portal: http://localhost:8080/portal/

### Demo operators (seeded on API startup — demo only)

| Username         | Password                   | Tenant  |
|------------------|----------------------------|---------|
| operator_admin   | secure_cleartext_password  | BANK001 |
| operator_bank2   | secure_cleartext_password  | BANK002 |
| operator_bank3   | secure_cleartext_password  | BANK003 |

Valid `loan_type` values: `RETAIL`, `COMMERCIAL`.

## Endpoints

### Gateway (`:8000`)

- Health: `GET /api/health/`
- Login (session cookie): `POST /api/auth/login` with `{"username", "password", "tenant_id"}` — sets HttpOnly session cookie; optional Bearer `token` in body for API tooling
- Session: `GET /api/auth/session`
- Logout: `POST /api/auth/logout`
- Trigger sync: `POST /api/sync` with `{"loan_type": "RETAIL"|"COMMERCIAL"}` (session cookie or Bearer JWT)
- Active sync: `GET /api/sync/active?loan_type=RETAIL`
- Job status: `GET /api/sync/status/<job_id>`
- Cancel sync: `POST /api/sync/cancel/<job_id>`
- Data snapshot: `GET /api/data?loan_type=RETAIL`
- Profiling: `GET /api/profiling?loan_type=RETAIL`

### Bank simulator (`:8080`)

- Health: `GET /health/`
- Upload CSV portfolio: `POST /api/bank/upload`
- Export credits (JSON stream): `GET /api/bank/export/credits?tenant_id=BANK001&loan_type=RETAIL`
- Export payments (JSON stream): `GET /api/bank/export/payments?tenant_id=BANK001&loan_type=RETAIL`

Bank APIs are intentionally unauthenticated for local simulation.

## Environment Variables

| Variable            | Default            | Description                |
|---------------------|--------------------|----------------------------|
| POSTGRES_USER       | teamsec            | Warehouse DB user          |
| POSTGRES_PASSWORD   | teamsec_secret     | Warehouse DB password      |
| POSTGRES_DB         | teamsec_warehouse  | Warehouse database name    |
| CELERY_BROKER_URL   | redis://redis_broker:6379/0 | Task queue URL |
| EXTERNAL_BANK_URL   | http://externalbank:8080 | Bank sim base URL (Compose alias) |

Default Django/JWT secret keys in Compose are demo-only — do not use outside local development.

## Known limitations

- Demo secrets, `DEBUG`, and open bank simulator are for local demos only.
- Bank export/upload APIs are intentionally unauthenticated.
- Sync uses Redis slice locks `lock:{tenant_id}:{loan_type}` (TTL 14400s / 4h). Parallel syncs are allowed across loan types for the same tenant.
- Sync cancel is cooperative: the progress callback polls a Redis cancel flag and Rust aborts before commit. Celery soft-revokes queued tasks; **PROCESSING** jobs keep the Redis slice lock until the worker exits so a re-sync cannot overwrite mid-rollback.
- API tests expect reachable Redis and Postgres (as configured in settings).
- The API image builds the Rust adapter for a shared Dockerfile layout; only the worker needs `adapter_core` at runtime.
- Warehouse snapshot money fields are serialized as decimal strings (not floats). Profiling aggregates remain IEEE floats for charting.

## Development

```bash
# Rebuild / refresh only the worker after Rust changes
docker compose build background_worker
docker compose up -d --force-recreate --no-deps background_worker

# Rust unit tests (stream/parser/pipeline); needs local Rust toolchain or CI
cd adapter && cargo test --lib && cd ..

# API orchestration tests (needs Redis + Postgres)
cd api && python manage.py test tests -v 2 && cd ..

# Bank simulator tests (local only — not in CI)
cd external_bank && python -m pytest ../tests/test_external_bank.py -v && cd ..

# Optional smoke (adapter_core installed):
# pytest tests/test_rust_adapter.py -v
```

CI (`.github/workflows/ci.yml`) runs Rust `cargo test --lib` and Django API tests with Postgres + Redis. Bank pytest and adapter smoke are local.

API tooling: Postman collection at `api/core_backend_api.postman_collection.json`.

See [Architecture.md](./Architecture.md) for the full system design map.
