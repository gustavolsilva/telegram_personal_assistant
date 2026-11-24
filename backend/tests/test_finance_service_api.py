"""Testes da camada de serviço e API REST do Módulo Financeiro."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from core.database import DatabaseManager
from fastapi import FastAPI
from modules.finance.api import create_finance_router
from modules.finance.seed import seed_defaults
from modules.finance.service import FinanceService, TransactionInput


@pytest.mark.asyncio
async def test_finance_service_and_rest_api(tmp_path) -> None:
    db = DatabaseManager(f"sqlite+aiosqlite:///{tmp_path / 'api_test.db'}")
    await db.create_tables()
    async with db.session_factory() as session:
        await seed_defaults(session)

    service = FinanceService(db.session_factory, storage=None)
    app = FastAPI()
    app.include_router(create_finance_router(service))

    try:
        cats, accs = await service.get_match_targets()
        food_cat = next(c for c in cats if c.name == "Alimentação")
        sal_cat = next(c for c in cats if c.name == "Salário")
        main_acc = accs[0]

        now = datetime.now(UTC)
        await service.create_transaction(
            TransactionInput(
                tx_type="income",
                amount_cents=500000,
                description="Salário mensal",
                category_id=sal_cat.id,
                account_id=main_acc.id,
                occurred_at=now,
            )
        )
        await service.create_transaction(
            TransactionInput(
                tx_type="expense",
                amount_cents=10000,
                description="Almoço",
                category_id=food_cat.id,
                account_id=main_acc.id,
                occurred_at=now,
            )
        )

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            summary_res = await client.get("/api/finance/summary")
            assert summary_res.status_code == 200
            summary = summary_res.json()
            assert summary["income_cents"] == 500000
            assert summary["expense_cents"] == 10000
            assert summary["balance_cents"] == 490000

            daily_res = await client.get("/api/finance/charts/daily")
            assert daily_res.status_code == 200
            assert len(daily_res.json()["days"]) >= 28

            monthly_res = await client.get("/api/finance/charts/monthly?months=6")
            assert monthly_res.status_code == 200
            assert len(monthly_res.json()) == 6

            cats_res = await client.get("/api/finance/charts/categories")
            assert cats_res.status_code == 200
            assert cats_res.json()[0]["name"] == "Alimentação"

            create_res = await client.post(
                "/api/finance/transactions",
                json={
                    "tx_type": "expense",
                    "amount_cents": 2500,
                    "description": "Café",
                    "category_id": food_cat.id,
                    "account_id": main_acc.id,
                },
            )
            assert create_res.status_code == 201
            tx_id = create_res.json()["id"]

            del_res = await client.delete(f"/api/finance/transactions/{tx_id}")
            assert del_res.status_code == 200
    finally:
        await db.dispose()

