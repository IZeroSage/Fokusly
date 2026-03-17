# Fokusly Backend (FastAPI)

Backend for the Fokusly iOS app based on `FastAPI_TZ.md`.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Run with Docker (backend + PostgreSQL)

```bash
cp .env.example .env
docker compose up --build
```

Backend:
- `http://127.0.0.1:8000`
- Docs: `http://127.0.0.1:8000/docs`

Stop and remove containers:

```bash
docker compose down
```

Stop and remove containers + DB volume:

```bash
docker compose down -v
```

## API docs

- Swagger UI: `http://127.0.0.1:8000/docs`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

## Architecture

```
app/
  api/v1/endpoints/   # routers grouped by domain
  core/               # config, errors, security
  db/                 # SQLAlchemy engine/session/base
  models/             # ORM entities
  schemas/            # request/response DTO
  services/           # shared helpers/serializers
  main.py             # app factory + startup
```

## Notes

- Base path: `/api/v1`
- Auth: Bearer token (`Authorization: Bearer <access_token>`)
- Default local DB: SQLite file `fokusly.db` (`DATABASE_URL` can override).
- In Docker, DB is PostgreSQL (`db` service) and persists in `postgres_data` volume.
