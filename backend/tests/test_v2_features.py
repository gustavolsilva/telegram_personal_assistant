"""Testes da v2 (Onda 1 + Onda 2): categorias, faturas de cartão, saldo previsto e orçamentos."""

from __future__ import annotations

from datetime import UTC, datetime

from app import create_app
from core.config import get_settings
from fastapi.testclient import TestClient


def test_v2_categories_invoices_projected_balance_and_budgets(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'v2.db'}")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("WEB_ACCESS_TOKEN", "")
    get_settings.cache_clear()
    try:
        app = create_app()
        with TestClient(app) as client:
            # 1. Criar categoria customizada e atualizar palavras-chave
            cat_res = client.post(
                "/api/finance/categories",
                json={
                    "name": "Pets",
                    "type": "expense",
                    "icon": "🐶",
                    "color": "#f97316",
                    "keywords": ["racao", "petshop"],
                },
            )
            assert cat_res.status_code == 201
            pet_cat = cat_res.json()
            assert pet_cat["name"] == "Pets"

            upd_cat = client.patch(
                f"/api/finance/categories/{pet_cat['id']}",
                json={"keywords": ["racao", "veterinario"]},
            )
            assert upd_cat.status_code == 200
            assert "veterinario" in upd_cat.json()["keywords"]

            # 2. Criar cartão com closing_day=10 e limite R$ 2.000
            card_res = client.post(
                "/api/finance/accounts",
                json={
                    "name": "Nubank Black",
                    "type": "credit",
                    "closing_day": 10,
                    "due_day": 17,
                    "credit_limit_cents": 200_000,
                },
            )
            assert card_res.status_code == 201
            card_id = card_res.json()["id"]

            accs = client.get("/api/finance/accounts").json()
            checking = next(a for a in accs if a["name"] == "Conta Principal")

            # Receita de R$ 1.000 efetivada + Despesa pendente R$ 200
            client.post(
                "/api/finance/transactions",
                json={
                    "tx_type": "income",
                    "amount_cents": 100_000,
                    "description": "Salário",
                    "category_id": next(
                        c["id"] for c in client.get("/api/finance/categories").json() if c["type"] == "income"
                    ),
                    "account_id": checking["id"],
                    "is_paid": True,
                },
            )
            client.post(
                "/api/finance/transactions",
                json={
                    "tx_type": "expense",
                    "amount_cents": 20_000,
                    "description": "Conta pendente",
                    "category_id": pet_cat["id"],
                    "account_id": checking["id"],
                    "is_paid": False,
                },
            )

            bal = client.get("/api/finance/balances").json()
            assert bal["total_available_cents"] == 100_000
            assert bal["projected_total_available_cents"] == 80_000

            # 3. Compra no cartão antes e depois do fechamento (dia 10)
            now = datetime.now(UTC)
            before_close = now.replace(day=5, hour=12, minute=0, second=0, microsecond=0)
            after_close = now.replace(day=15, hour=12, minute=0, second=0, microsecond=0)

            client.post(
                "/api/finance/transactions",
                json={
                    "tx_type": "expense",
                    "amount_cents": 30_000,
                    "description": "Ração",
                    "category_id": pet_cat["id"],
                    "account_id": card_id,
                    "occurred_at": before_close.isoformat(),
                },
            )
            client.post(
                "/api/finance/transactions",
                json={
                    "tx_type": "expense",
                    "amount_cents": 15_000,
                    "description": "Banho pet",
                    "category_id": pet_cat["id"],
                    "account_id": card_id,
                    "occurred_at": after_close.isoformat(),
                },
            )

            cur_month = f"{now.year:04d}-{now.month:02d}"
            inv = client.get(f"/api/finance/cards/{card_id}/invoice?month={cur_month}").json()
            assert inv["total_cents"] == 30_000
            assert inv["remaining_cents"] == 30_000

            pay_res = client.post(
                f"/api/finance/cards/{card_id}/pay",
                json={"month": cur_month, "from_account_id": checking["id"]},
            )
            assert pay_res.status_code == 200
            inv_paid = client.get(f"/api/finance/cards/{card_id}/invoice?month={cur_month}").json()
            assert inv_paid["remaining_cents"] == 0
            assert inv_paid["status"] == "paid"

            # 4. Orçamento por categoria (Pets gastou R$ 650 no mês vs teto R$ 500 -> exceeded)
            bdg_res = client.put(
                f"/api/finance/budgets/{pet_cat['id']}",
                json={"limit_cents": 50_000},
            )
            assert bdg_res.status_code == 200
            assert bdg_res.json()["status"] == "exceeded"
            assert bdg_res.json()["spent_cents"] == 65_000
    finally:
        get_settings.cache_clear()
