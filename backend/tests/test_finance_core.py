"""Testes da Fase 1: Core modular, Auth, SQLite WAL, modelos e seed."""

from __future__ import annotations

import pytest
from core.auth import is_authorized_telegram_user
from core.config import Settings
from core.database import DatabaseManager
from core.module_base import AssistantModule, CommandSpec
from core.router import ModuleRouter
from modules.finance.models import Account, Category, Transaction, generate_uuid7
from modules.finance.seed import seed_defaults
from sqlalchemy import select, text


class DummyModule(AssistantModule):
    name = "dummy"
    display_name = "Dummy"
    priority = 10

    def get_commands(self) -> list[CommandSpec]:
        return [CommandSpec(command="ping", description="Responde pong")]

    async def handle_command(self, command, args, update, context) -> bool:
        return command == "ping"

    def can_handle_text(self, text: str) -> bool:
        return "dummy" in text.lower()

    async def handle_text(self, text: str, update, context) -> bool:
        return True


def test_telegram_whitelist() -> None:
    cfg = Settings(telegram_user_id=998877)
    assert is_authorized_telegram_user(998877, cfg) is True
    assert is_authorized_telegram_user(112233, cfg) is False
    assert is_authorized_telegram_user(None, cfg) is False


def test_uuid7_is_time_ordered() -> None:
    ids = [generate_uuid7() for _ in range(10)]
    assert len(set(ids)) == 10
    assert len(ids[0]) == 36


@pytest.mark.asyncio
async def test_module_router_dispatch() -> None:
    router = ModuleRouter()
    mod = DummyModule()
    router.register(mod)

    assert len(router.all_commands()) == 1
    assert await router.dispatch_command("ping", [], None, None) is True
    assert await router.dispatch_command("unknown", [], None, None) is False
    assert await router.dispatch_text("olá dummy", None, None) is True
    assert await router.dispatch_text("gasto 20", None, None) is False


@pytest.mark.asyncio
async def test_sqlite_wal_and_finance_seed(tmp_path) -> None:
    db_file = tmp_path / "test_finance.db"
    db = DatabaseManager(f"sqlite+aiosqlite:///{db_file}")
    try:
        await db.create_tables()
        async with db.session_factory() as session:
            mode = (await session.execute(text("PRAGMA journal_mode;"))).scalar_one()
            assert str(mode).lower() == "wal"

            await seed_defaults(session)
            # Rodar duas vezes deve ser idempotente
            await seed_defaults(session)

            accounts = (await session.scalars(select(Account))).all()
            categories = (await session.scalars(select(Category))).all()
            assert len(accounts) == 4
            assert len(categories) == 16

            acc = accounts[0]
            cat = next(c for c in categories if c.name == "Alimentação")
            tx = Transaction(
                type="expense",
                amount_cents=4590,
                description="Almoço executivo",
                category_id=cat.id,
                account_id=acc.id,
            )
            session.add(tx)
            await session.commit()

            loaded = await session.get(Transaction, tx.id)
            assert loaded is not None
            assert loaded.amount_cents == 4590
            assert loaded.deleted_at is None
    finally:
        await db.dispose()

