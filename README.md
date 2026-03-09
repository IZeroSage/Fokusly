# Fokusly Backend (FastAPI)

MVP backend for the Fokusly iOS app based on `FastAPI_TZ.md`.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## API docs

- Swagger UI: `http://127.0.0.1:8000/docs`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

## Notes

- Base path: `/api/v1`
- Auth: Bearer token (`Authorization: Bearer <access_token>`)
- Storage: in-memory (for MVP/prototyping). Data resets on restart.
