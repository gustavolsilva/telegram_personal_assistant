"""Testes unitários para múltiplos cartões com vencimento, contas fixas (água/luz/internet/aluguel) e veículo (IPVA)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import httpx
import pytest
from core.database import DatabaseManager
from core.router import ModuleRouter
from fastapi import FastAPI
from modules.finance.api import create_finance_router
from modules.finance.handlers import FinanceModule
from modules.finance.seed import seed_defaults
from modules.finance.service import FinanceService, TransactionInput


def _msg_update(text: str, msg_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=123),
        effective_message=SimpleNamespace(
            text=text,
            message_id=msg_id,
            reply_html=AsyncMock(),
            reply_text=AsyncMock(),
        ),
        callback_query=None,
    )


@pytest.mark.asyncio
async def test_multi_cards_due_dates_fixed_bills_and_vehicle(tmp_path) -> None:
    db = DatabaseManager(f"sqlite+aiosqlite:///{tmp_path / 'bills_cards.db'}")
    await db.create_tables()
    async with db.session_factory() as session:
        await seed_defaults(session)

    service = FinanceService(db.session_factory, storage=None)
    app = FastAPI()
    app.include_router(create_finance_router(service))
    module = FinanceModule(service=service)
    router = ModuleRouter()
    router.register(module)

    try:
        # 1. Criar segundo cartão com vencimento próximo (daqui a 2 dias)
        now = datetime.now(UTC)
        due_day = min(28, now.day + 2)
        upd_card = _msg_update(f"/novo_cartao Inter {due_day}")
        assert await router.dispatch_command("novo_cartao", ["Inter", str(due_day)], cast(Any, upd_card), cast(Any, None)) is True
        assert "Inter" in upd_card.effective_message.reply_html.call_args.args[0]

        # Registrar gasto no novo cartão
        cats, accs = await service.get_match_targets()
        inter_acc = next(a for a in accs if a.name == "Inter")
        moradia_cat = next(c for c in cats if c.name == "Moradia")
        veiculo_cat = next(c for c in cats if c.name == "Veículo")
        main_acc = next(a for a in accs if a.name == "Conta Principal")

        await service.create_transaction(
            TransactionInput(
                tx_type="expense",
                amount_cents=35000,
                description="Compra Inter",
                category_id=moradia_cat.id,
                account_id=inter_acc.id,
                occurred_at=now,
            )
        )

        # 2. Cadastrar contas fixas (Água, Luz, Internet, Aluguel) + anual (IPVA) via API
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for name, cents in [
                ("Água (Saneamento)", 9500),
                ("Energia Elétrica", 18000),
                ("Internet Fixa", 11990),
                ("Aluguel", 180000),
            ]:
                r = await client.post(
                    "/api/finance/bills",
                    json={
                        "name": name,
                        "amount_cents": cents,
                        "due_day": due_day,
                        "recurrence": "monthly",
                        "category_id": moradia_cat.id,
                        "account_id": main_acc.id,
                    },
                )
                assert r.status_code == 201

            r_ipva = await client.post(
                "/api/finance/bills",
                json={
                    "name": "IPVA + Licenciamento",
                    "amount_cents": 120000,
                    "due_day": due_day,
                    "due_month": now.month,
                    "recurrence": "yearly",
                    "category_id": veiculo_cat.id,
                    "account_id": main_acc.id,
                },
            )
            assert r_ipva.status_code == 201

            # Verificar lembretes de vencimentos (/api/finance/upcoming)
            upcoming = (await client.get("/api/finance/upcoming")).json()
            titles = [u["title"] for u in upcoming]
            assert any("Fatura Inter" in t for t in titles)
            assert any("Água" in t for t in titles)
            assert any("IPVA" in t for t in titles)

            # Pagar uma conta fixa via API
            bills = (await client.get("/api/finance/bills")).json()
            agua = next(b for b in bills if "Água" in b["name"])
            pay_res = await client.post(f"/api/finance/bills/{agua['id']}/pay")
            assert pay_res.status_code == 200

            bills_after = (await client.get("/api/finance/bills")).json()
            agua_after = next(b for b in bills_after if b["id"] == agua["id"])
            assert agua_after["status"] == "paid"

        # 3. Testar /vencimentos e /fixas no Bot
        upd_v = _msg_update("/vencimentos")
        assert await router.dispatch_command("vencimentos", [], cast(Any, upd_v), cast(Any, None)) is True
        assert "Fatura Inter" in upd_v.effective_message.reply_html.call_args.args[0]

        upd_f = _msg_update("/fixas")
        assert await router.dispatch_command("fixas", [], cast(Any, upd_f), cast(Any, None)) is True
        assert "Energia Elétrica" in upd_f.effective_message.reply_html.call_args.args[0]

        # 4. Cadastrar nova conta bancária e nova conta fixa direto pelo Bot
        upd_nc = _msg_update("/nova_conta Bradesco 1500")
        assert await router.dispatch_command("nova_conta", ["Bradesco", "1500"], cast(Any, upd_nc), cast(Any, None)) is True
        assert "Bradesco" in upd_nc.effective_message.reply_html.call_args.args[0]

        upd_nf = _msg_update("/nova_fixa Internet Móvel 79,90 12")
        assert await router.dispatch_command("nova_fixa", ["Internet", "Móvel", "79,90", "12"], cast(Any, upd_nf), cast(Any, None)) is True
        assert "Internet Móvel" in upd_nf.effective_message.reply_html.call_args.args[0]
    finally:
        await db.dispose()

