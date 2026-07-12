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
# From the repository root (parent of project/)
bash init_project.sh

cd project
docker compose up --build
```

## Endpoints

- Gateway health: `GET http://localhost:8000/api/health/`
- Issue JWT: `POST http://localhost:8000/api/auth/token/` with `{"tenant_id": "tenant_alpha"}`
- ETL dashboard (HTMX): `http://localhost:8000/etl/`
- Trigger ETL job: `POST http://localhost:8000/etl/jobs/trigger/`
- Bank simulator: `GET http://localhost:8080/api/v1/loans/tenant_alpha/`

## Environment Variables

| Variable            | Default            | Description                |
|---------------------|--------------------|----------------------------|
| POSTGRES_USER       | teamsec            | Warehouse DB user          |
| POSTGRES_PASSWORD   | teamsec_secret     | Warehouse DB password      |
| POSTGRES_DB         | teamsec_warehouse  | Warehouse database name    |
| CELERY_BROKER_URL   | redis://redis_broker:6379/0 | Task queue URL |
| EXTERNAL_BANK_URL   | http://external_bank_sim:8080 | Bank sim base URL |

## Development

```bash
# Rebuild only the worker after Rust changes
docker compose build background_worker
docker compose up -d background_worker

# Run Rust adapter unit test locally (requires maturin + built wheel)
cd adapter && maturin develop && cd ..
pytest tests/test_rust_adapter.py -v
```

See [Architecture.md](./Architecture.md) for the full system design map.
