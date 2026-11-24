"""Testes unitários para saldos em contas, transferências, parcelamentos no cartão e perguntas naturais."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from core.database import DatabaseManager
from core.router import ModuleRouter
from fastapi import FastAPI
from modules.finance.api import create_finance_router
from modules.finance.handlers import FinanceModule
from modules.finance.seed import seed_defaults
from modules.finance.service import FinanceService


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
async def test_balances_transfers_installments_and_bot_questions(tmp_path) -> None:
    db = DatabaseManager(f"sqlite+aiosqlite:///{tmp_path / 'fin_adv.db'}")
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
        # 1. Ajustar saldo inicial da Conta Principal para R$ 2.000,00 via comando
        upd_adj = _msg_update("/ajustar_saldo Conta Principal 2000")
        assert await router.dispatch_command("ajustar_saldo", ["Conta", "Principal", "2000"], upd_adj, None) is True  # type: ignore[arg-type]
        assert "R$ 2.000,00" in upd_adj.effective_message.reply_html.call_args.args[0]

        # 2. Transferir R$ 500,00 da Conta Principal para o Pix
        upd_tr = _msg_update("transferi 500 da conta principal para pix")
        assert await router.dispatch_text(upd_tr.effective_message.text, upd_tr, None) is True  # type: ignore[arg-type]
        assert "cadastrada no Aplicativo com sucesso" in upd_tr.effective_message.reply_html.call_args.args[0]
        assert "Ver no App" in upd_tr.effective_message.reply_html.call_args.args[0]

        # 3. Compra parcelada no cartão: 600 celular 6x cartão
        upd_inst = _msg_update("600 celular 6x cartão")
        assert await router.dispatch_text(upd_inst.effective_message.text, upd_inst, None) is True  # type: ignore[arg-type]
        inst_reply = upd_inst.effective_message.reply_html.call_args.args[0]
        assert "6x de R$ 100,00" in inst_reply
        assert "R$ 600,00" in inst_reply

        # 4. Pergunta em linguagem natural sobre saldo
        upd_q = _msg_update("Quanto de saldo em conta eu tenho?")
        assert await router.dispatch_text(upd_q.effective_message.text, upd_q, None) is True  # type: ignore[arg-type]
        q_reply = upd_q.effective_message.reply_html.call_args.args[0]
        assert "Conta Principal:" in q_reply
        assert "R$ 1.500,00" in q_reply
        assert "Pix:" in q_reply
        assert "R$ 500,00" in q_reply
        assert "Total Disponível em Contas:" in q_reply
        assert "R$ 2.000,00" in q_reply
        assert "Parcelas futuras R$ 500,00" in q_reply

        # 5. Comando /parcelas
        upd_p = _msg_update("/parcelas")
        assert await router.dispatch_command("parcelas", [], upd_p, None) is True  # type: ignore[arg-type]
        p_reply = upd_p.effective_message.reply_html.call_args.args[0]
        assert "6x de R$ 100,00" in p_reply
        assert "Restam 5 (R$ 500,00)" in p_reply

        # 6. Validar endpoints REST (/balances, /installments e /summary sem inflar transferência)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            bal = (await client.get("/api/finance/balances")).json()
            assert bal["total_available_cents"] == 200000
            assert bal["credit_used_cents"] == 10000
            assert bal["credit_future_installments_cents"] == 50000

            insts = (await client.get("/api/finance/installments")).json()
            assert len(insts) == 1
            assert insts[0]["remaining_cents"] == 50000

            summary = (await client.get("/api/finance/summary")).json()
            # Transferência não infla receita/despesa; apenas a 1ª parcela (100,00) entra no mês atual
            assert summary["income_cents"] == 0
            assert summary["expense_cents"] == 10000
    finally:
        await db.dispose()

