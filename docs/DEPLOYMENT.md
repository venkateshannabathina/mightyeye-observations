# Running, persistence and operations

## Local demo

`./scripts/run_demo.sh` generates and verifies synthetic sources before starting the dashboard on loopback. A separate process can start an existing demo without rebuilding clips:

```sh
export DATABASE_URL=sqlite:///output/demo/mightyeye.db
export EVIDENCE_ROOT=output/demo/evidence
export MIGHTYEYE_MODE=synthetic
.venv/bin/mightyeye-observations serve --port 8000
```

The demo database and generated media are ignored by Git. Use another output folder for a fresh independent run. The script accepts `PYTHON_BIN`, relative `DEMO_OUTPUT`, and `PORT` environment overrides.

## PostgreSQL

```sh
cp .env.example .env
# Set a URL-safe local POSTGRES_PASSWORD.
docker compose up --build
```

PostgreSQL data and evidence use named volumes. The app is exposed on `127.0.0.1:8000`; PostgreSQL is internal to Compose. The default mode is live, with no synthetic seed.

### Seed a dedicated synthetic PostgreSQL deployment

Before creating the database's first observations, set `MIGHTYEYE_MODE=synthetic` in `.env`, then:

```sh
docker compose up -d db
docker compose run --rm app sh -c 'mightyeye-observations demo --output /app/output --database-url "$DATABASE_URL"'
docker compose up -d app
```

Do not reuse a live-mode database for synthetic data. Startup checks the stored rule configuration and mode. Use separate Compose project names/volumes for separate deployments, or provision a new database. Do not delete an existing database to switch modes casually.

## Configuration and schema

- `DATABASE_URL`: SQLAlchemy URL; use `postgresql+psycopg://...` for deployment.
- `EVIDENCE_ROOT`: allowed root for registered evidence media.
- `MIGHTYEYE_MODE`: `live` or `synthetic`.
- `MIGHTYEYE_RULES`: path to validated rule configuration.

The six domain tables and `schema_settings` are created idempotently at schema v2. Startup includes an explicit v1→v2 migration that backfills numeric alert trigger times for correct chronological ordering. Add reviewed migrations for future structural changes; unknown schema versions fail startup. Changing temporal rules requires a new version and a new replay/deployment database in this prototype.

## Restart and single-writer operation

Observations, incidents, evidence references, entity enrichments and reviews are durable. Startup replays stored observations in insertion order to reconstruct temporal state. IDs prevent duplicated observation ingestion from producing duplicate incidents. Each ingestion transaction commits before its in-memory state is published.

Run exactly **one backend worker**. The in-memory engine, per-process lock and WebSocket subscriptions are not a distributed state service. Current replay startup scales with observation history; checkpointing, retention and durable queues are future operations work.

## API boundary

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/cameras` | Observation sources and reported health |
| GET | `/world` | Current tracks |
| GET | `/incidents` | Type/camera filtering and limit/offset pagination |
| GET | `/incidents/{id}` | Facts, evidence, reviews and optional inference |
| GET | `/evidence/{id}` | MP4 with Range support; `?frame=true` returns the trigger frame |
| GET | `/health` | Backend and reported stream metrics |
| WS | `/live` | Initial snapshots and world/incident/health updates |
| POST | `/observations` | Validated producer input |
| POST | `/cameras/{id}/health` | Runtime telemetry |
| POST | `/incidents/{id}/reviews` | Confirmed / False / Uncertain review |
| POST | `/appearances` | Provenanced appearance vectors |
| POST | `/plates` | Provenanced plate result |
| POST | `/incidents/{id}/verify` | Optional provider verification; disabled by default |

See `/docs` for request schemas. WebSocket queues are bounded; slow clients must recover missed incident history through REST. World updates are full snapshots. In synthetic mode no feeds are claimed to be live.

## Evidence and backup

Keep database backups and media backups consistent. Evidence paths are relative to a configured root, and lookup checks the resolved path stays within that root. MP4s are separate files with hashes and coverage metadata. Missing media returns 404 rather than a fabricated replacement. An expired/deleted file does not delete the incident's history.

Use `pg_dump` for PostgreSQL and back up the evidence volume. Restore into a separate deployment and verify sample incident/video/review records before trusting the backup.

## Local access boundary

This hackathon backend has no user authentication and is intentionally loopback-only in supplied launch settings. Add authentication, authorization, TLS and protected ingestion before making it network-accessible to untrusted clients. Avoid multiple workers until state ownership is redesigned.
