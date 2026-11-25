"""Endpoints REST do Módulo Financeiro para o Dashboard Web PWA."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from core.auth import verify_web_access_token
from core.telegram_storage import format_brl_cents
from core.voice import normalize_spoken_ptbr
from fastapi import APIRouter, Depends, HTTPException, Query
from modules.finance.parser import parse_finance_question, parse_ptbr_transaction
from modules.finance.service import FinanceService, TransactionInput
from pydantic import BaseModel, Field


class TransactionCreateBody(BaseModel):
    tx_type: str = Field(pattern="^(expense|income|transfer)$")
    amount_cents: int = Field(gt=0)
    description: str = Field(min_length=1, max_length=255)
    category_id: str
    account_id: str
    transfer_to_account_id: str | None = None
    installments_total: int = Field(default=1, ge=1, le=48)
    occurred_at: datetime | None = None
    notes: str | None = None
    is_paid: bool = True
    billing_month: str | None = None


class TransactionUpdateBody(BaseModel):
    tx_type: str | None = Field(default=None, pattern="^(expense|income|transfer)$")
    amount_cents: int | None = Field(default=None, gt=0)
    description: str | None = Field(default=None, min_length=1, max_length=255)
    category_id: str | None = None
    account_id: str | None = None
    occurred_at: datetime | None = None
    notes: str | None = None
    is_paid: bool | None = None
    billing_month: str | None = None


class CategoryCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    type: str = Field(default="expense", pattern="^(expense|income)$")
    icon: str = Field(default="📦", max_length=16)
    color: str = Field(default="#64748b", max_length=16)
    keywords: list[str] = Field(default_factory=list)


class CategoryUpdateBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    icon: str | None = Field(default=None, max_length=16)
    color: str | None = Field(default=None, max_length=16)
    keywords: list[str] | None = None


class AccountUpdateBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    color: str | None = None
    closing_day: int | None = Field(default=None, ge=1, le=31)
    due_day: int | None = Field(default=None, ge=1, le=31)
    credit_limit_cents: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class PayInvoiceBody(BaseModel):
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    from_account_id: str
    amount_cents: int | None = Field(default=None, gt=0)


class BudgetUpsertBody(BaseModel):
    limit_cents: int = Field(ge=0)


class BalanceAdjustBody(BaseModel):
    target_balance_cents: int


class AccountCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    type: str = Field(default="credit", pattern="^(checking|credit|wallet|savings)$")
    color: str = Field(default="#6366f1")
    initial_balance_cents: int = 0
    closing_day: int | None = Field(default=None, ge=1, le=31)
    due_day: int | None = Field(default=None, ge=1, le=31)
    credit_limit_cents: int = Field(default=0, ge=0)


class RecurringBillCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    amount_cents: int = Field(gt=0)
    due_day: int = Field(ge=1, le=31)
    due_month: int | None = Field(default=None, ge=1, le=12)
    recurrence: str = Field(default="monthly", pattern="^(monthly|yearly)$")
    category_id: str
    account_id: str


class PayBillBody(BaseModel):
    amount_cents: int | None = Field(default=None, gt=0)
    account_id: str | None = None


class ChatMessageBody(BaseModel):
    message: str = Field(min_length=1, max_length=500)


def _serialize_tx(tx: Any) -> dict[str, Any]:
    return {
        "id": tx.id,
        "type": tx.type,
        "amount_cents": tx.amount_cents,
        "currency": tx.currency,
        "description": tx.description,
        "category_id": tx.category_id,
        "category_name": tx.category.name if tx.category else "",
        "category_icon": tx.category.icon if tx.category else "📦",
        "category_color": tx.category.color if tx.category else "#64748b",
        "account_id": tx.account_id,
        "account_name": tx.account.name if tx.account else "",
        "occurred_at": tx.occurred_at.isoformat(),
        "is_paid": getattr(tx, "is_paid", True),
        "billing_month": getattr(tx, "billing_month", None),
        "source": tx.source,
        "installment_number": tx.installment_number,
        "installment_total": tx.installment_total,
        "transfer_to_account_id": tx.transfer_to_account_id,
        "has_receipt": bool(tx.receipt_file_id),
        "channel_msg_id": tx.channel_msg_id,
        "notes": tx.notes,
        "created_at": tx.created_at.isoformat(),
    }


def _default_month_range() -> tuple[datetime, datetime]:
    now = datetime.now(UTC)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, now


def create_finance_router(service: FinanceService) -> APIRouter:
    router = APIRouter(
        prefix="/api/finance",
        tags=["finance"],
        dependencies=[Depends(verify_web_access_token)],
    )

    @router.get("/summary")
    async def get_summary(
        start: datetime | None = Query(default=None),
        end: datetime | None = Query(default=None),
    ) -> dict[str, Any]:
        def_start, def_end = _default_month_range()
        return await service.get_summary(start or def_start, end or def_end)

    @router.get("/charts/daily")
    async def get_daily_chart(
        year: int | None = Query(default=None, ge=2000, le=2100),
        month: int | None = Query(default=None, ge=1, le=12),
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        return await service.get_daily_series(year or now.year, month or now.month)

    @router.get("/charts/monthly")
    async def get_monthly_chart(months: int = Query(default=6, ge=2, le=24)) -> list[dict[str, Any]]:
        return await service.get_monthly_series(months=months)

    @router.get("/charts/categories")
    async def get_categories_chart(
        start: datetime | None = Query(default=None),
        end: datetime | None = Query(default=None),
        tx_type: str = Query(default="expense", pattern="^(expense|income)$"),
    ) -> list[dict[str, Any]]:
        def_start, def_end = _default_month_range()
        return await service.get_category_breakdown(start or def_start, end or def_end, tx_type)

    @router.get("/charts/weekdays")
    async def get_weekdays_chart(
        start: datetime | None = Query(default=None),
        end: datetime | None = Query(default=None),
    ) -> list[dict[str, Any]]:
        def_start, def_end = _default_month_range()
        return await service.get_weekday_pattern(start or def_start, end or def_end)

    @router.get("/transactions")
    async def list_transactions(
        start: datetime | None = Query(default=None),
        end: datetime | None = Query(default=None),
        tx_type: str | None = Query(default=None, pattern="^(expense|income)$"),
        category_id: str | None = Query(default=None),
        account_id: str | None = Query(default=None),
        search: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> list[dict[str, Any]]:
        items = await service.list_transactions(
            start=start,
            end=end,
            tx_type=tx_type,
            category_id=category_id,
            account_id=account_id,
            search=search,
            limit=limit,
            offset=offset,
        )
        return [_serialize_tx(tx) for tx in items]

    @router.post("/transactions", status_code=201)
    async def create_transaction(body: TransactionCreateBody) -> dict[str, Any]:
        tx = await service.create_transaction(
            TransactionInput(
                tx_type=body.tx_type,
                amount_cents=body.amount_cents,
                description=body.description,
                category_id=body.category_id,
                account_id=body.account_id,
                transfer_to_account_id=body.transfer_to_account_id,
                installments_total=body.installments_total,
                occurred_at=body.occurred_at,
                source="web",
                notes=body.notes,
                is_paid=body.is_paid,
                billing_month=body.billing_month,
            )
        )
        return _serialize_tx(tx)

    @router.patch("/transactions/{tx_id}")
    async def update_transaction(tx_id: str, body: TransactionUpdateBody) -> dict[str, Any]:
        updated = await service.update_transaction(
            tx_id,
            tx_type=body.tx_type,
            amount_cents=body.amount_cents,
            description=body.description,
            category_id=body.category_id,
            account_id=body.account_id,
            occurred_at=body.occurred_at,
            notes=body.notes,
            is_paid=body.is_paid,
            billing_month=body.billing_month,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="Lançamento não encontrado.")
        return _serialize_tx(updated)

    @router.delete("/transactions/{tx_id}")
    async def delete_transaction(tx_id: str) -> dict[str, bool]:
        ok = await service.soft_delete_transaction(tx_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Lançamento não encontrado.")
        return {"deleted": True}

    @router.get("/categories")
    async def list_categories() -> list[dict[str, Any]]:
        cats = await service.list_categories()
        return [
            {
                "id": c.id,
                "name": c.name,
                "type": c.type,
                "icon": c.icon,
                "color": c.color,
                "keywords": json.loads(c.keywords_json or "[]"),
            }
            for c in cats
        ]

    @router.post("/categories", status_code=201)
    async def create_category(body: CategoryCreateBody) -> dict[str, Any]:
        cat = await service.create_category(
            name=body.name,
            cat_type=body.type,
            icon=body.icon,
            color=body.color,
            keywords=body.keywords,
        )
        return {
            "id": cat.id,
            "name": cat.name,
            "type": cat.type,
            "icon": cat.icon,
            "color": cat.color,
            "keywords": json.loads(cat.keywords_json or "[]"),
        }

    @router.patch("/categories/{category_id}")
    async def update_category(category_id: str, body: CategoryUpdateBody) -> dict[str, Any]:
        cat = await service.update_category(
            category_id,
            name=body.name,
            icon=body.icon,
            color=body.color,
            keywords=body.keywords,
        )
        if cat is None:
            raise HTTPException(status_code=404, detail="Categoria não encontrada.")
        return {
            "id": cat.id,
            "name": cat.name,
            "type": cat.type,
            "icon": cat.icon,
            "color": cat.color,
            "keywords": json.loads(cat.keywords_json or "[]"),
        }

    @router.delete("/categories/{category_id}")
    async def delete_category(category_id: str) -> dict[str, bool]:
        ok, err = await service.delete_category(category_id)
        if not ok:
            raise HTTPException(status_code=400, detail=err)
        return {"deleted": True}

    @router.get("/accounts")
    async def list_accounts() -> list[dict[str, Any]]:
        accs = await service.list_accounts()
        return [
            {
                "id": a.id,
                "name": a.name,
                "type": a.type,
                "color": a.color,
                "initial_balance_cents": a.initial_balance_cents,
                "closing_day": a.closing_day,
                "due_day": a.due_day,
                "credit_limit_cents": a.credit_limit_cents,
                "is_active": a.is_active,
            }
            for a in accs
            if a.is_active
        ]

    @router.post("/accounts", status_code=201)
    async def create_account(body: AccountCreateBody) -> dict[str, Any]:
        acc = await service.create_account(
            name=body.name,
            acc_type=body.type,
            color=body.color,
            initial_balance_cents=body.initial_balance_cents,
            closing_day=body.closing_day,
            due_day=body.due_day,
            credit_limit_cents=body.credit_limit_cents,
        )
        return {
            "id": acc.id,
            "name": acc.name,
            "type": acc.type,
            "due_day": acc.due_day,
            "credit_limit_cents": acc.credit_limit_cents,
        }

    @router.patch("/accounts/{account_id}")
    async def update_account(account_id: str, body: AccountUpdateBody) -> dict[str, Any]:
        acc = await service.update_account(
            account_id,
            name=body.name,
            color=body.color,
            closing_day=body.closing_day,
            due_day=body.due_day,
            credit_limit_cents=body.credit_limit_cents,
            is_active=body.is_active,
        )
        if acc is None:
            raise HTTPException(status_code=404, detail="Conta não encontrada.")
        return {"id": acc.id, "name": acc.name, "is_active": acc.is_active}

    @router.get("/cards/{account_id}/invoice")
    async def get_card_invoice(
        account_id: str,
        month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    ) -> dict[str, Any]:
        inv = await service.get_card_invoice(account_id, month=month)
        if inv is None:
            raise HTTPException(status_code=404, detail="Cartão não encontrado.")
        return {
            **{k: v for k, v in inv.items() if k != "transactions"},
            "transactions": [_serialize_tx(tx) for tx in inv["transactions"]],
        }

    @router.post("/cards/{account_id}/pay")
    async def pay_card_invoice(account_id: str, body: PayInvoiceBody) -> dict[str, Any]:
        tx = await service.pay_card_invoice(
            account_id,
            month=body.month,
            from_account_id=body.from_account_id,
            amount_cents=body.amount_cents,
        )
        if tx is None:
            raise HTTPException(status_code=400, detail="Fatura vazia ou cartão inválido.")
        return _serialize_tx(tx)

    @router.get("/budgets")
    async def list_budgets() -> list[dict[str, Any]]:
        return await service.list_budgets()

    @router.put("/budgets/{category_id}")
    async def upsert_budget(category_id: str, body: BudgetUpsertBody) -> dict[str, Any]:
        res = await service.upsert_budget(category_id, body.limit_cents)
        if res is None:
            raise HTTPException(status_code=404, detail="Categoria não encontrada.")
        return res

    @router.get("/bills")
    async def list_bills() -> list[dict[str, Any]]:
        return await service.list_recurring_bills()

    @router.post("/bills", status_code=201)
    async def create_bill(body: RecurringBillCreateBody) -> dict[str, Any]:
        bill = await service.create_recurring_bill(
            name=body.name,
            amount_cents=body.amount_cents,
            due_day=body.due_day,
            due_month=body.due_month,
            recurrence=body.recurrence,
            category_id=body.category_id,
            account_id=body.account_id,
        )
        return {"id": bill.id, "name": bill.name}

    @router.post("/bills/{bill_id}/pay")
    async def pay_bill(bill_id: str, body: PayBillBody | None = None) -> dict[str, Any]:
        tx = await service.pay_recurring_bill(
            bill_id,
            amount_cents=body.amount_cents if body else None,
            account_id=body.account_id if body else None,
        )
        if tx is None:
            raise HTTPException(status_code=404, detail="Conta fixa não encontrada.")
        return _serialize_tx(tx)

    @router.delete("/bills/{bill_id}")
    async def delete_bill(bill_id: str) -> dict[str, bool]:
        ok = await service.delete_recurring_bill(bill_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Conta fixa não encontrada.")
        return {"deleted": True}

    @router.get("/upcoming")
    async def get_upcoming_dues() -> list[dict[str, Any]]:
        return await service.get_upcoming_dues(days_ahead=7)

    @router.get("/balances")
    async def get_balances() -> dict[str, Any]:
        return await service.get_account_balances()

    @router.patch("/accounts/{account_id}/balance")
    async def adjust_account_balance(account_id: str, body: BalanceAdjustBody) -> dict[str, Any]:
        acc = await service.adjust_account_balance(account_id, body.target_balance_cents)
        if acc is None:
            raise HTTPException(status_code=404, detail="Conta não encontrada.")
        return await service.get_account_balances()

    @router.get("/installments")
    async def get_installments() -> list[dict[str, Any]]:
        return await service.get_active_installments()

    @router.post("/chat")
    async def chat_with_assistant(body: ChatMessageBody) -> dict[str, Any]:
        """Mecanismo conversacional unificado no Dashboard (estilo regis.chat)."""
        text = normalize_spoken_ptbr(body.message)
        cats, accs = await service.get_match_targets()

        question = parse_finance_question(text, accs)
        if question is not None:
            if question.intent == "balance":
                data = await service.get_account_balances()
                accounts = data["accounts"]
                if question.account_hint:
                    hint_l = question.account_hint.lower()
                    filtered = [a for a in accounts if hint_l in a["name"].lower()]
                    if filtered:
                        accounts = filtered
                lines = ["🏦 Saldos em Contas:"]
                for a in accounts:
                    if a["type"] == "credit":
                        used = max(0, a["expenses_cents"] - a["incomes_cents"] - a["initial_balance_cents"])
                        lines.append(
                            f"• {a['name']}: Fatura {format_brl_cents(used)} | Parcelas futuras {format_brl_cents(a['future_installments_cents'])}"
                        )
                    else:
                        lines.append(f"• {a['name']}: {format_brl_cents(a['balance_cents'])}")
                if not question.account_hint:
                    lines.append(f"\n💰 Total Disponível: {format_brl_cents(data['total_available_cents'])}")
                return {"reply": "\n".join(lines), "refresh": False}

            if question.intent == "installments":
                items = await service.get_active_installments()
                active = [i for i in items if i["remaining_installments"] > 0 or i["total_installments"] > 1]
                if not active:
                    return {"reply": "💳 Nenhum parcelamento ativo no momento.", "refresh": False}
                tot = sum(i["remaining_cents"] for i in active)
                lines = ["💳 Parcelamentos Acumulados:"]
                for i in active[:8]:
                    lines.append(
                        f"• {i['description']} ({i['account_name']}): {i['total_installments']}x de {format_brl_cents(i['installment_amount_cents'])} · Restam {i['remaining_installments']} ({format_brl_cents(i['remaining_cents'])})"
                    )
                lines.append(f"\n📌 Total futuro: {format_brl_cents(tot)}")
                return {"reply": "\n".join(lines), "refresh": False}

            now = datetime.now(UTC)
            start = (
                now.replace(hour=0, minute=0, second=0, microsecond=0)
                if question.intent == "summary_today"
                else now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            )
            s = await service.get_summary(start, now)
            label = "Hoje" if question.intent == "summary_today" else "Mês Atual"
            return {
                "reply": (
                    f"📊 Resumo ({label}):\n"
                    f"🟢 Ganhos: {format_brl_cents(s['income_cents'])}\n"
                    f"🔴 Gastos: {format_brl_cents(s['expense_cents'])}\n"
                    f"💰 Saldo: {format_brl_cents(s['balance_cents'])}"
                ),
                "refresh": False,
            }

        parsed = parse_ptbr_transaction(text, cats, accs)
        if parsed is None or parsed.category_id is None or parsed.account_id is None:
            return {
                "reply": (
                    "Não entendi o lançamento ou pergunta. Tente:\n"
                    "• '45,90 almoço nubank'\n"
                    "• '600 celular 6x cartão'\n"
                    "• 'Qual meu saldo?'"
                ),
                "refresh": False,
            }

        tx_input = TransactionInput(
            tx_type=parsed.tx_type,
            amount_cents=parsed.amount_cents,
            description=parsed.description,
            category_id=parsed.category_id,
            account_id=parsed.account_id,
            occurred_at=parsed.occurred_at,
            source="web_chat",
            installments_total=parsed.installments_total,
            transfer_to_account_id=parsed.transfer_to_account_id,
        )
        if parsed.installments_total > 1:
            created = await service.create_installments(tx_input)
            first = created[0]
            return {
                "reply": (
                    f"💳 Parcelamento registrado!\n"
                    f"{parsed.description}: {parsed.installments_total}x de {format_brl_cents(first.amount_cents)} "
                    f"(Total: {format_brl_cents(parsed.amount_cents)})"
                ),
                "refresh": True,
            }

        tx = await service.create_transaction(tx_input)
        emoji = "🔁" if tx.type == "transfer" else ("🟢" if tx.type == "income" else "🔴")
        return {
            "reply": f"{emoji} Registrado: {tx.description} · {format_brl_cents(tx.amount_cents)} ({tx.account.name})",
            "refresh": True,
        }

    @router.get("/sync-status")
    async def get_sync_status() -> dict[str, Any]:
        state = await service.get_sync_state()
        return {
            "channel_configured": service.storage is not None,
            "pinned_msg_id": state.pinned_msg_id if state else None,
            "last_synced_at": state.last_synced_at.isoformat() if state and state.last_synced_at else None,
            "checksum_sha256": state.checksum_sha256 if state else None,
        }

    @router.post("/sync-now")
    async def trigger_sync_now() -> dict[str, Any]:
        if service.storage is None:
            raise HTTPException(status_code=400, detail="Canal de storage não configurado.")
        snap = await service.storage.upload_snapshot_now()
        await service.record_sync_state(
            pinned_msg_id=snap.pinned_msg_id,
            file_id=snap.file_id,
            checksum_sha256=snap.checksum_sha256,
            synced_at=snap.synced_at,
        )
        return {
            "pinned_msg_id": snap.pinned_msg_id,
            "size_bytes": snap.size_bytes,
            "synced_at": snap.synced_at.isoformat(),
        }

    return router

