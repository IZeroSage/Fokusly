# Fokusly Backend

Бэкенд для приложения Fokusly на FastAPI.

## Из чего состоит

- API версии `v1` с префиксом `/api/v1`
- JWT-аутентификация (`Bearer <access_token>`)
- SQLAlchemy + SQLite локально
- PostgreSQL при запуске через Docker Compose

Документация:
- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/openapi.json`

## Запуск в Docker

```bash
cp .env.example .env
docker compose up -d --build
```

Остановка:

```bash
docker compose down
```

Остановка с удалением volume базы:

```bash
docker compose down -v
```

## Структура проекта

```text
app/
  api/v1/endpoints/
  core/
  db/
  models/
  schemas/
  services/
  main.py
```

## Переменные окружения

- `DATABASE_URL` — строка подключения к БД
- `FOKUSLY_SECRET_KEY` — ключ подписи токенов
- `ACCESS_TOKEN_TTL_MINUTES` — TTL access token
- `REFRESH_TOKEN_TTL_DAYS` — TTL refresh token

Для Docker Compose используются:
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
