"""Gerenciamento de conexão SQLite (WAL) e Neon Postgres (asyncpg) com sessões assíncronas."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from core.config import get_settings
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool


class Base(DeclarativeBase):
    """Classe base para todas as entidades ORM."""


def normalize_database_url(raw_url: str) -> tuple[str, dict[str, Any]]:
    """Normaliza URLs do SQLite ou Postgres/Neon para SQLAlchemy async."""
    url = raw_url.strip()
    if url.startswith("sqlite"):
        return url, {}

    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]

    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    connect_args: dict[str, Any] = {}

    sslmode = qs.pop("sslmode", [None])[0]
    qs.pop("channel_binding", None)
    if sslmode in ("require", "verify-ca", "verify-full") or "neon.tech" in (parsed.hostname or ""):
        connect_args["ssl"] = "require"

    clean_query = urlencode({k: v[0] for k, v in qs.items() if v})
    normalized = urlunparse(parsed._replace(query=clean_query))
    return normalized, connect_args


def _configure_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("PRAGMA temp_store=MEMORY;")
    cursor.close()


class DatabaseManager:
    """Encapsula engine e sessionmaker para SQLite local e Postgres serverless."""

    def __init__(self, database_url: str) -> None:
        normalized_url, connect_args = normalize_database_url(database_url)
        self.is_sqlite = normalized_url.startswith("sqlite")

        if self.is_sqlite and normalized_url.startswith("sqlite+aiosqlite:///") and not normalized_url.endswith(
            ":memory:"
        ):
            raw_path = normalized_url.removeprefix("sqlite+aiosqlite:///")
            Path(raw_path).parent.mkdir(parents=True, exist_ok=True)

        engine_kwargs: dict[str, Any] = {"echo": False}
        if not self.is_sqlite:
            # Em ambientes serverless (Vercel), NullPool evita conexões órfãs no Neon
            engine_kwargs["poolclass"] = NullPool
            if connect_args:
                engine_kwargs["connect_args"] = connect_args

        self.engine: AsyncEngine = create_async_engine(normalized_url, **engine_kwargs)
        if self.is_sqlite:
            event.listen(self.engine.sync_engine, "connect", _configure_sqlite_pragmas)

        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )

    async def create_tables(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            if self.is_sqlite:
                await conn.run_sync(self._migrate_missing_columns)
            else:
                await conn.run_sync(self._migrate_postgres_columns)

    @staticmethod
    def _migrate_missing_columns(sync_conn) -> None:
        """Garante evolução segura do schema SQLite sem perder dados existentes."""
        existing_acc = {
            row[1] for row in sync_conn.exec_driver_sql("PRAGMA table_info(accounts)").fetchall()
        }
        if existing_acc:
            for col_name, col_def in [
                ("initial_balance_cents", "INTEGER NOT NULL DEFAULT 0"),
                ("closing_day", "INTEGER"),
                ("due_day", "INTEGER"),
                ("credit_limit_cents", "INTEGER NOT NULL DEFAULT 0"),
            ]:
                if col_name not in existing_acc:
                    sync_conn.exec_driver_sql(
                        f"ALTER TABLE accounts ADD COLUMN {col_name} {col_def}"
                    )

        existing_tx = {
            row[1] for row in sync_conn.exec_driver_sql("PRAGMA table_info(transactions)").fetchall()
        }
        if existing_tx:
            for col_name, col_def in [
                ("transfer_to_account_id", "VARCHAR(36)"),
                ("installment_group_id", "VARCHAR(36)"),
                ("installment_number", "INTEGER"),
                ("installment_total", "INTEGER"),
                ("is_paid", "BOOLEAN NOT NULL DEFAULT 1"),
                ("billing_month", "VARCHAR(7)"),
                ("external_fitid", "VARCHAR(120)"),
                ("tags_json", "TEXT NOT NULL DEFAULT '[]'"),
            ]:
                if col_name not in existing_tx:
                    sync_conn.exec_driver_sql(
                        f"ALTER TABLE transactions ADD COLUMN {col_name} {col_def}"
                    )

    @staticmethod
    def _migrate_postgres_columns(sync_conn) -> None:
        """Garante evolução segura do schema Postgres/Neon sem perder dados existentes."""
        sync_conn.exec_driver_sql(
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS is_paid BOOLEAN NOT NULL DEFAULT TRUE"
        )
        sync_conn.exec_driver_sql(
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS billing_month VARCHAR(7)"
        )
        sync_conn.exec_driver_sql(
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS external_fitid VARCHAR(120)"
        )
        sync_conn.exec_driver_sql(
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS tags_json TEXT NOT NULL DEFAULT '[]'"
        )

    async def dispose(self) -> None:
        await self.engine.dispose()

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.session_factory() as sess:
            yield sess


_default_db: DatabaseManager | None = None


def get_db_manager() -> DatabaseManager:
    global _default_db
    if _default_db is None:
        _default_db = DatabaseManager(get_settings().effective_database_url)
    return _default_db


async def get_db_session() -> AsyncIterator[AsyncSession]:
    db = get_db_manager()
    async with db.session_factory() as sess:
        yield sess
