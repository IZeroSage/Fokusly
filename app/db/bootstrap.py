from __future__ import annotations

from sqlalchemy import text

from app.db.session import engine


def ensure_runtime_schema() -> None:
    with engine.begin() as connection:
        dialect = connection.dialect.name
        if dialect == "postgresql":
            connection.execute(
                text(
                    "ALTER TABLE user_settings "
                    "ADD COLUMN IF NOT EXISTS timezone VARCHAR(64) NOT NULL DEFAULT 'Europe/Moscow'"
                )
            )
            return
        if dialect == "sqlite":
            columns = connection.execute(text("PRAGMA table_info(user_settings)")).all()
            has_timezone = any(str(row[1]) == "timezone" for row in columns)
            if not has_timezone:
                connection.execute(
                    text(
                        "ALTER TABLE user_settings "
                        "ADD COLUMN timezone VARCHAR(64) NOT NULL DEFAULT 'Europe/Moscow'"
                    )
                )
