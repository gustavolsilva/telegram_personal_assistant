"""Popula o banco local (data/assistant.db) com dados realistas de demonstração."""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import get_settings
from core.database import DatabaseManager
from modules.finance.seed import seed_defaults
from modules.finance.service import FinanceService, TransactionInput


async def run_demo_seed() -> None:
    cfg = get_settings()
    db = DatabaseManager(cfg.database_url)
    await db.create_tables()
    async with db.session_factory() as session:
        await seed_defaults(session)

    service = FinanceService(db.session_factory, storage=None)
    existing = await service.list_transactions(limit=5)
    if existing:
        print(f"Banco já possui {len(existing)}+ lançamentos. Pulando duplicação.")
        await db.dispose()
        return

    cats, accs = await service.get_match_targets()
    cat_by_name = {c.name: c.id for c in cats}
    acc_by_name = {a.name: a.id for a in accs}

    # Ajustar saldos iniciais e criar segundo cartão
    await service.adjust_account_balance(acc_by_name["Conta Principal"], 325000)
    await service.adjust_account_balance(acc_by_name["Pix"], 98000)
    await service.adjust_account_balance(acc_by_name["Carteira"], 24000)
    inter = await service.create_account(
        name="Inter Black", acc_type="credit", due_day=min(28, datetime.now(UTC).day + 3)
    )

    now = datetime.now(UTC)

    # Histórico dos últimos 5 meses + mês atual
    for m_offset in range(5, -1, -1):
        ref = now - timedelta(days=30 * m_offset)
        month_start = ref.replace(day=1, hour=10, minute=0, second=0, microsecond=0)

        samples = [
            ("income", 680000, "Salário mensal", "Salário", "Conta Principal", 4),
            ("income", 125000, "Projeto Freelance", "Freelance", "Pix", 14),
            ("expense", 185000, "Aluguel apartamento", "Moradia", "Conta Principal", 5),
            ("expense", 19500, "Energia Elétrica", "Moradia", "Pix", 9),
            ("expense", 11990, "Internet Fibra", "Moradia", "Pix", 10),
            ("expense", 68000 + (m_offset * 3500), "Supermercado do mês", "Mercado", "Cartão de Crédito", 7),
            ("expense", 42000 + (m_offset * 2000), "Restaurantes & iFood", "Alimentação", "Cartão de Crédito", 12),
            ("expense", 24000, "Uber & Combustível", "Transporte", "Cartão de Crédito", 16),
            ("expense", 12990, "Streaming & Assinaturas", "Assinaturas", "Cartão de Crédito", 18),
            ("expense", 18500, "Farmácia & Academia", "Saúde", "Pix", 20),
            ("expense", 26000, "Cinema e Lazer", "Lazer", "Carteira", 22),
        ]
        for tx_type, cents, desc, cat_name, acc_name, day_num in samples:
            occ = month_start + timedelta(days=min(day_num - 1, 25))
            if occ > now:
                continue
            await service.create_transaction(
                TransactionInput(
                    tx_type=tx_type,
                    amount_cents=cents,
                    description=desc,
                    category_id=cat_by_name[cat_name],
                    account_id=acc_by_name[acc_name],
                    occurred_at=occ,
                    source="demo_seed",
                )
            )

    # Parcelamento ativo no cartão
    await service.create_installments(
        TransactionInput(
            tx_type="expense",
            amount_cents=270000,
            description="Notebook Trabalho",
            category_id=cat_by_name["Educação"],
            account_id=inter.id,
            occurred_at=now - timedelta(days=2),
            installments_total=6,
            source="demo_seed",
        )
    )

    # Contas fixas + anual (IPVA)
    due_soon = min(28, now.day + 3)
    for b_name, cents, d_day, rec, d_month, cat_n in [
        ("Água (Saneamento)", 9450, due_soon, "monthly", None, "Moradia"),
        ("Energia Elétrica (Luz)", 19800, due_soon + 1 if due_soon < 28 else 28, "monthly", None, "Moradia"),
        ("Internet Fixa Fibra", 11990, 10, "monthly", None, "Moradia"),
        ("Internet Móvel 5G", 7990, 15, "monthly", None, "Assinaturas"),
        ("Aluguel / Financiamento", 185000, 5, "monthly", None, "Moradia"),
        ("IPVA + Licenciamento", 135000, due_soon, "yearly", now.month, "Veículo"),
    ]:
        await service.create_recurring_bill(
            name=b_name,
            amount_cents=cents,
            due_day=d_day,
            due_month=d_month,
            recurrence=rec,
            category_id=cat_by_name[cat_n],
            account_id=acc_by_name["Conta Principal"],
        )

    print("Dados de demonstração populados com sucesso em data/assistant.db!")
    await db.dispose()


if __name__ == "__main__":
    asyncio.run(run_demo_seed())

