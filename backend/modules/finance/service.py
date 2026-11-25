"""Camada de serviço e consultas analíticas do Módulo Financeiro."""

from __future__ import annotations

import calendar
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from core.telegram_storage import TelegramStorageManager
from modules.finance.models import (
    Account,
    Category,
    CategoryBudget,
    RecurringBill,
    SyncState,
    Transaction,
    generate_uuid7,
)
from modules.finance.parser import AccountMatchTarget, CategoryMatchTarget
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload


def _add_months(dt: datetime, months: int) -> datetime:
    total_months = (dt.year * 12 + (dt.month - 1)) + months
    year = total_months // 12
    month = (total_months % 12) + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def _billing_month_for(dt: datetime, closing_day: int | None) -> str:
    """Determina a competência (YYYY-MM) da fatura com base no dia de fechamento."""
    ref = dt
    if closing_day is not None and 1 <= closing_day <= 31 and ref.day >= closing_day:
        ref = _add_months(ref.replace(day=1), 1)
    return f"{ref.year:04d}-{ref.month:02d}"


@dataclass(slots=True)
class TransactionInput:
    tx_type: str
    amount_cents: int
    description: str
    category_id: str
    account_id: str
    occurred_at: datetime | None = None
    source: str = "telegram_text"
    source_msg_id: int | None = None
    notes: str | None = None
    installments_total: int = 1
    transfer_to_account_id: str | None = None
    is_paid: bool = True
    billing_month: str | None = None


class FinanceService:
    """Regras de negócio compartilhadas entre o Bot do Telegram e a API Web."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        storage: TelegramStorageManager | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.storage = storage

    async def get_match_targets(
        self,
    ) -> tuple[list[CategoryMatchTarget], list[AccountMatchTarget]]:
        async with self.session_factory() as session:
            cats = (await session.scalars(select(Category).order_by(Category.name))).all()
            accs = (
                await session.scalars(
                    select(Account).where(Account.is_active.is_(True)).order_by(Account.name)
                )
            ).all()
            cat_targets = [
                CategoryMatchTarget(
                    id=c.id,
                    name=c.name,
                    type=c.type,
                    keywords=json.loads(c.keywords_json or "[]"),
                )
                for c in cats
            ]
            acc_targets = [AccountMatchTarget(id=a.id, name=a.name, type=a.type) for a in accs]
            return cat_targets, acc_targets

    async def create_transaction(
        self,
        data: TransactionInput,
        *,
        photo_bytes: bytes | None = None,
        voice_bytes: bytes | None = None,
    ) -> Transaction:
        if data.installments_total > 1:
            created = await self.create_installments(data, photo_bytes=photo_bytes)
            return created[0]

        async with self.session_factory() as session:
            occ_dt = data.occurred_at or datetime.now(UTC)
            bill_month = data.billing_month
            if bill_month is None:
                acc = await session.get(Account, data.account_id)
                if acc is not None and acc.type == "credit":
                    bill_month = _billing_month_for(occ_dt, acc.closing_day)

            tx = Transaction(
                type=data.tx_type,
                amount_cents=data.amount_cents,
                description=data.description,
                category_id=data.category_id,
                account_id=data.account_id,
                transfer_to_account_id=data.transfer_to_account_id,
                occurred_at=occ_dt,
                is_paid=data.is_paid,
                billing_month=bill_month,
                source=data.source,
                source_msg_id=data.source_msg_id,
                notes=data.notes,
            )
            session.add(tx)
            await session.commit()

            loaded = await self._load_tx(session, tx.id)
            assert loaded is not None

            if self.storage is not None:
                post_res = await self.storage.post_transaction(
                    self._to_channel_payload(loaded),
                    photo_bytes=photo_bytes,
                    voice_bytes=voice_bytes,
                )
                loaded.channel_msg_id = post_res.channel_msg_id
                loaded.receipt_file_id = post_res.file_id
                loaded.receipt_file_unique_id = post_res.file_unique_id
                await session.commit()
                self.storage.schedule_snapshot()

            return loaded

    async def create_installments(
        self,
        data: TransactionInput,
        *,
        photo_bytes: bytes | None = None,
    ) -> list[Transaction]:
        total_n = max(2, data.installments_total)
        base_cents = data.amount_cents // total_n
        rem_cents = data.amount_cents % total_n
        group_id = generate_uuid7()
        start_dt = data.occurred_at or datetime.now(UTC)

        created_ids: list[str] = []
        async with self.session_factory() as session:
            acc = await session.get(Account, data.account_id)
            closing_day = acc.closing_day if acc is not None and acc.type == "credit" else None
            is_credit = acc is not None and acc.type == "credit"
            for idx in range(total_n):
                part_cents = base_cents + (rem_cents if idx == 0 else 0)
                part_dt = _add_months(start_dt, idx)
                part_bill = _billing_month_for(part_dt, closing_day) if is_credit else None
                tx_id = generate_uuid7()
                tx = Transaction(
                    id=tx_id,
                    type=data.tx_type,
                    amount_cents=part_cents,
                    description=f"{data.description} ({idx + 1}/{total_n})",
                    category_id=data.category_id,
                    account_id=data.account_id,
                    occurred_at=part_dt,
                    is_paid=data.is_paid,
                    billing_month=part_bill,
                    source=data.source,
                    source_msg_id=data.source_msg_id,
                    installment_group_id=group_id,
                    installment_number=idx + 1,
                    installment_total=total_n,
                    notes=data.notes,
                )
                session.add(tx)
                created_ids.append(tx_id)
            await session.commit()

            loaded_list: list[Transaction] = []
            for tx_id in created_ids:
                loaded = await self._load_tx(session, tx_id)
                if loaded is not None:
                    loaded_list.append(loaded)

            if self.storage is not None and loaded_list:
                # Posta a 1a parcela (ou resumo) no canal para respeitar rate limit
                first = loaded_list[0]
                post_res = await self.storage.post_transaction(
                    self._to_channel_payload(first),
                    photo_bytes=photo_bytes,
                )
                first.channel_msg_id = post_res.channel_msg_id
                first.receipt_file_id = post_res.file_id
                first.receipt_file_unique_id = post_res.file_unique_id
                await session.commit()
                self.storage.schedule_snapshot()

            return loaded_list

    async def update_transaction(
        self,
        tx_id: str,
        *,
        tx_type: str | None = None,
        amount_cents: int | None = None,
        description: str | None = None,
        category_id: str | None = None,
        account_id: str | None = None,
        occurred_at: datetime | None = None,
        notes: str | None = None,
        is_paid: bool | None = None,
        billing_month: str | None = None,
    ) -> Transaction | None:
        async with self.session_factory() as session:
            tx = await self._load_tx(session, tx_id)
            if tx is None or tx.deleted_at is not None:
                return None

            if tx_type is not None:
                tx.type = tx_type
            if amount_cents is not None:
                tx.amount_cents = amount_cents
            if description is not None:
                tx.description = description
            if category_id is not None:
                tx.category_id = category_id
            if account_id is not None:
                tx.account_id = account_id
            if occurred_at is not None:
                tx.occurred_at = occurred_at
            if notes is not None:
                tx.notes = notes
            if is_paid is not None:
                tx.is_paid = is_paid
            if billing_month is not None:
                tx.billing_month = billing_month

            await session.commit()
            tx = await self._load_tx(session, tx_id)
            assert tx is not None

            if self.storage is not None and tx.channel_msg_id is not None:
                await self.storage.update_transaction_message(
                    tx.channel_msg_id,
                    self._to_channel_payload(tx),
                    has_media=tx.receipt_file_id is not None,
                )
                self.storage.schedule_snapshot()

            return tx

    async def soft_delete_transaction(self, tx_id: str) -> bool:
        async with self.session_factory() as session:
            tx = await self._load_tx(session, tx_id)
            if tx is None or tx.deleted_at is not None:
                return False

            tx.deleted_at = datetime.now(UTC)
            await session.commit()

            if self.storage is not None and tx.channel_msg_id is not None:
                await self.storage.update_transaction_message(
                    tx.channel_msg_id,
                    self._to_channel_payload(tx, deleted=True),
                    has_media=tx.receipt_file_id is not None,
                )
                self.storage.schedule_snapshot()

            return True

    async def get_transaction(self, tx_id: str) -> Transaction | None:
        async with self.session_factory() as session:
            tx = await self._load_tx(session, tx_id)
            if tx is None or tx.deleted_at is not None:
                return None
            return tx

    async def list_transactions(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        tx_type: str | None = None,
        category_id: str | None = None,
        account_id: str | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Transaction]:
        async with self.session_factory() as session:
            conds = [Transaction.deleted_at.is_(None)]
            if start is not None:
                conds.append(Transaction.occurred_at >= start)
            if end is not None:
                conds.append(Transaction.occurred_at <= end)
            if tx_type:
                conds.append(Transaction.type == tx_type)
            if category_id:
                conds.append(Transaction.category_id == category_id)
            if account_id:
                conds.append(Transaction.account_id == account_id)
            if search:
                conds.append(Transaction.description.ilike(f"%{search.strip()}%"))

            stmt = (
                select(Transaction)
                .options(
                    selectinload(Transaction.category),
                    selectinload(Transaction.account),
                    selectinload(Transaction.transfer_to_account),
                )
                .where(and_(*conds))
                .order_by(Transaction.occurred_at.desc(), Transaction.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            return list((await session.scalars(stmt)).all())

    async def get_summary(self, start: datetime, end: datetime) -> dict[str, Any]:
        period_delta = end - start
        prev_end = start - timedelta(seconds=1)
        prev_start = prev_end - period_delta

        async with self.session_factory() as session:
            cur_rows = (
                await session.execute(
                    select(Transaction.type, Transaction.amount_cents).where(
                        Transaction.deleted_at.is_(None),
                        Transaction.occurred_at >= start,
                        Transaction.occurred_at <= end,
                    )
                )
            ).all()

            prev_rows = (
                await session.execute(
                    select(Transaction.type, Transaction.amount_cents).where(
                        Transaction.deleted_at.is_(None),
                        Transaction.occurred_at >= prev_start,
                        Transaction.occurred_at <= prev_end,
                    )
                )
            ).all()

        income = sum(r.amount_cents for r in cur_rows if r.type == "income")
        expense = sum(r.amount_cents for r in cur_rows if r.type == "expense")
        balance = income - expense
        savings_rate = round(((income - expense) / income) * 100, 1) if income > 0 else 0.0

        prev_income = sum(r.amount_cents for r in prev_rows if r.type == "income")
        prev_expense = sum(r.amount_cents for r in prev_rows if r.type == "expense")
        prev_balance = prev_income - prev_expense

        def pct_change(cur: int, prev: int) -> float | None:
            if prev == 0:
                return None if cur == 0 else 100.0
            return round(((cur - prev) / abs(prev)) * 100, 1)

        return {
            "income_cents": income,
            "expense_cents": expense,
            "balance_cents": balance,
            "savings_rate_pct": savings_rate,
            "count": len(cur_rows),
            "income_change_pct": pct_change(income, prev_income),
            "expense_change_pct": pct_change(expense, prev_expense),
            "balance_change_pct": pct_change(balance, prev_balance),
        }

    async def get_daily_series(self, year: int, month: int) -> dict[str, Any]:
        days_in_month = calendar.monthrange(year, month)[1]
        cur_start = datetime(year, month, 1, 0, 0, 0, tzinfo=UTC)
        cur_end = datetime(year, month, days_in_month, 23, 59, 59, tzinfo=UTC)

        prev_month = 12 if month == 1 else month - 1
        prev_year = year - 1 if month == 1 else year
        prev_days = calendar.monthrange(prev_year, prev_month)[1]
        prev_start = datetime(prev_year, prev_month, 1, 0, 0, 0, tzinfo=UTC)
        prev_end = datetime(prev_year, prev_month, prev_days, 23, 59, 59, tzinfo=UTC)

        async with self.session_factory() as session:
            cur_txs = (
                await session.execute(
                    select(Transaction.occurred_at, Transaction.type, Transaction.amount_cents).where(
                        Transaction.deleted_at.is_(None),
                        Transaction.occurred_at >= cur_start,
                        Transaction.occurred_at <= cur_end,
                    )
                )
            ).all()
            prev_txs = (
                await session.execute(
                    select(Transaction.occurred_at, Transaction.type, Transaction.amount_cents).where(
                        Transaction.deleted_at.is_(None),
                        Transaction.occurred_at >= prev_start,
                        Transaction.occurred_at <= prev_end,
                    )
                )
            ).all()

        cur_income = [0] * days_in_month
        cur_expense = [0] * days_in_month
        for row in cur_txs:
            if row.type == "transfer":
                continue
            idx = row.occurred_at.day - 1
            if 0 <= idx < days_in_month:
                if row.type == "income":
                    cur_income[idx] += row.amount_cents
                elif row.type == "expense":
                    cur_expense[idx] += row.amount_cents

        prev_expense_by_day = [0] * max(days_in_month, prev_days)
        for row in prev_txs:
            if row.type == "expense":
                idx = row.occurred_at.day - 1
                if 0 <= idx < len(prev_expense_by_day):
                    prev_expense_by_day[idx] += row.amount_cents

        series = []
        cum_balance = 0
        cum_cur_exp = 0
        cum_prev_exp = 0
        for d in range(days_in_month):
            cum_balance += cur_income[d] - cur_expense[d]
            cum_cur_exp += cur_expense[d]
            cum_prev_exp += prev_expense_by_day[d]
            series.append(
                {
                    "day": d + 1,
                    "income_cents": cur_income[d],
                    "expense_cents": cur_expense[d],
                    "cumulative_balance_cents": cum_balance,
                    "cumulative_expense_cents": cum_cur_exp,
                    "prev_month_cumulative_expense_cents": cum_prev_exp,
                }
            )

        return {"year": year, "month": month, "days": series}

    async def get_monthly_series(self, months: int = 6) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        # Calcula lista dos últimos N meses
        ym_list: list[tuple[int, int]] = []
        y, m = now.year, now.month
        for _ in range(months):
            ym_list.append((y, m))
            m -= 1
            if m == 0:
                m = 12
                y -= 1
        ym_list.reverse()

        first_y, first_m = ym_list[0]
        range_start = datetime(first_y, first_m, 1, 0, 0, 0, tzinfo=UTC)

        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(Transaction.occurred_at, Transaction.type, Transaction.amount_cents).where(
                        Transaction.deleted_at.is_(None),
                        Transaction.occurred_at >= range_start,
                    )
                )
            ).all()

        buckets: dict[tuple[int, int], dict[str, int]] = {
            ym: {"income_cents": 0, "expense_cents": 0} for ym in ym_list
        }
        for row in rows:
            if row.type == "transfer":
                continue
            key = (row.occurred_at.year, row.occurred_at.month)
            if key in buckets:
                if row.type == "income":
                    buckets[key]["income_cents"] += row.amount_cents
                elif row.type == "expense":
                    buckets[key]["expense_cents"] += row.amount_cents

        result = []
        for y, m in ym_list:
            inc = buckets[(y, m)]["income_cents"]
            exp = buckets[(y, m)]["expense_cents"]
            result.append(
                {
                    "year": y,
                    "month": m,
                    "label": f"{m:02d}/{y}",
                    "income_cents": inc,
                    "expense_cents": exp,
                    "net_cents": inc - exp,
                }
            )
        return result

    async def get_category_breakdown(
        self, start: datetime, end: datetime, tx_type: str = "expense"
    ) -> list[dict[str, Any]]:
        avg_start = start - timedelta(days=90)
        async with self.session_factory() as session:
            txs = (
                await session.execute(
                    select(
                        Transaction.category_id,
                        Transaction.amount_cents,
                        Transaction.occurred_at,
                    ).where(
                        Transaction.deleted_at.is_(None),
                        Transaction.type == tx_type,
                        Transaction.occurred_at >= avg_start,
                        Transaction.occurred_at <= end,
                    )
                )
            ).all()
            cats = {
                c.id: c
                for c in (
                    await session.scalars(select(Category).where(Category.type == tx_type))
                ).all()
            }

        cur_totals: dict[str, int] = {}
        hist_totals: dict[str, int] = {}
        start_utc = start if start.tzinfo else start.replace(tzinfo=UTC)
        for row in txs:
            occ = row.occurred_at if row.occurred_at.tzinfo else row.occurred_at.replace(tzinfo=UTC)
            if occ >= start_utc:
                cur_totals[row.category_id] = cur_totals.get(row.category_id, 0) + row.amount_cents
            else:
                hist_totals[row.category_id] = hist_totals.get(row.category_id, 0) + row.amount_cents

        grand_total = sum(cur_totals.values())
        items = []
        for cat_id, total in cur_totals.items():
            cat = cats.get(cat_id)
            if cat is None:
                continue
            avg_3m = hist_totals.get(cat_id, 0) // 3
            deviation_pct = (
                round(((total - avg_3m) / avg_3m) * 100, 1) if avg_3m > 0 else None
            )
            items.append(
                {
                    "category_id": cat.id,
                    "name": cat.name,
                    "icon": cat.icon,
                    "color": cat.color,
                    "total_cents": total,
                    "share_pct": round((total / grand_total) * 100, 1) if grand_total > 0 else 0.0,
                    "avg_3m_cents": avg_3m,
                    "deviation_vs_avg_pct": deviation_pct,
                }
            )
        items.sort(key=lambda x: x["total_cents"], reverse=True)
        return items

    async def get_weekday_pattern(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        labels = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
        totals = [0] * 7
        counts = [0] * 7

        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(Transaction.occurred_at, Transaction.amount_cents).where(
                        Transaction.deleted_at.is_(None),
                        Transaction.type == "expense",
                        Transaction.occurred_at >= start,
                        Transaction.occurred_at <= end,
                    )
                )
            ).all()

        for row in rows:
            wd = row.occurred_at.weekday()
            totals[wd] += row.amount_cents
            counts[wd] += 1

        return [
            {
                "weekday": i,
                "label": labels[i],
                "expense_cents": totals[i],
                "count": counts[i],
            }
            for i in range(7)
        ]

    async def list_categories(self) -> list[Category]:
        async with self.session_factory() as session:
            return list((await session.scalars(select(Category).order_by(Category.type, Category.name))).all())

    async def list_accounts(self) -> list[Account]:
        async with self.session_factory() as session:
            return list((await session.scalars(select(Account).order_by(Account.name))).all())

    async def get_account_balances(self, as_of: datetime | None = None) -> dict[str, Any]:
        """Calcula saldo real por conta, fatura de cartão e parcelamentos futuros acumulados."""
        ref_now = as_of or datetime.now(UTC)
        async with self.session_factory() as session:
            accounts = list(
                (await session.scalars(select(Account).where(Account.is_active.is_(True)).order_by(Account.name))).all()
            )
            txs = (
                await session.execute(
                    select(
                        Transaction.type,
                        Transaction.amount_cents,
                        Transaction.account_id,
                        Transaction.transfer_to_account_id,
                        Transaction.occurred_at,
                        Transaction.installment_group_id,
                        Transaction.is_paid,
                    ).where(Transaction.deleted_at.is_(None))
                )
            ).all()
            bills = list(
                (await session.scalars(select(RecurringBill).where(RecurringBill.is_active.is_(True)))).all()
            )

        acc_stats: dict[str, dict[str, int]] = {
            a.id: {
                "incomes_cents": 0,
                "expenses_cents": 0,
                "pending_incomes_cents": 0,
                "pending_expenses_cents": 0,
                "future_installments_cents": 0,
            }
            for a in accounts
        }

        end_of_month = _add_months(ref_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), 1)
        for row in txs:
            occ = row.occurred_at if row.occurred_at.tzinfo else row.occurred_at.replace(tzinfo=UTC)
            is_future = occ > ref_now
            if is_future:
                if row.type == "expense" and row.account_id in acc_stats:
                    acc_stats[row.account_id]["future_installments_cents"] += row.amount_cents
                if occ < end_of_month:
                    if row.type == "income" and row.account_id in acc_stats:
                        acc_stats[row.account_id]["pending_incomes_cents"] += row.amount_cents
                    elif row.type == "expense" and row.account_id in acc_stats:
                        acc_stats[row.account_id]["pending_expenses_cents"] += row.amount_cents
                continue

            if not getattr(row, "is_paid", True):
                if row.type == "income" and row.account_id in acc_stats:
                    acc_stats[row.account_id]["pending_incomes_cents"] += row.amount_cents
                elif row.type == "expense" and row.account_id in acc_stats:
                    acc_stats[row.account_id]["pending_expenses_cents"] += row.amount_cents
                continue

            if row.type == "income" and row.account_id in acc_stats:
                acc_stats[row.account_id]["incomes_cents"] += row.amount_cents
            elif row.type == "expense" and row.account_id in acc_stats:
                acc_stats[row.account_id]["expenses_cents"] += row.amount_cents
            elif row.type == "transfer":
                if row.account_id in acc_stats:
                    acc_stats[row.account_id]["expenses_cents"] += row.amount_cents
                if row.transfer_to_account_id and row.transfer_to_account_id in acc_stats:
                    acc_stats[row.transfer_to_account_id]["incomes_cents"] += row.amount_cents

        cur_period_m = ref_now.strftime("%Y-%m")
        cur_period_y = ref_now.strftime("%Y")
        unpaid_bills_cents = 0
        for b in bills:
            if b.recurrence == "yearly":
                if b.due_month == ref_now.month and b.last_paid_period != cur_period_y:
                    unpaid_bills_cents += b.amount_cents
            elif b.last_paid_period != cur_period_m:
                unpaid_bills_cents += b.amount_cents

        items = []
        total_available_cents = 0
        projected_delta_cents = -unpaid_bills_cents
        credit_used_cents = 0
        credit_future_cents = 0

        for acc in accounts:
            st = acc_stats[acc.id]
            balance_cents = acc.initial_balance_cents + st["incomes_cents"] - st["expenses_cents"]
            available_limit_cents: int | None = None
            if acc.type == "credit":
                used = max(0, st["expenses_cents"] - st["incomes_cents"] - acc.initial_balance_cents)
                credit_used_cents += used
                credit_future_cents += st["future_installments_cents"]
                if acc.credit_limit_cents > 0:
                    available_limit_cents = max(
                        0, acc.credit_limit_cents - used - st["future_installments_cents"]
                    )
            else:
                total_available_cents += balance_cents
                projected_delta_cents += st["pending_incomes_cents"] - st["pending_expenses_cents"]

            items.append(
                {
                    "id": acc.id,
                    "name": acc.name,
                    "type": acc.type,
                    "color": acc.color,
                    "initial_balance_cents": acc.initial_balance_cents,
                    "closing_day": acc.closing_day,
                    "due_day": acc.due_day,
                    "credit_limit_cents": acc.credit_limit_cents,
                    "available_limit_cents": available_limit_cents,
                    "incomes_cents": st["incomes_cents"],
                    "expenses_cents": st["expenses_cents"],
                    "balance_cents": balance_cents,
                    "future_installments_cents": st["future_installments_cents"],
                }
            )

        return {
            "total_available_cents": total_available_cents,
            "projected_total_available_cents": total_available_cents + projected_delta_cents,
            "unpaid_bills_cents": unpaid_bills_cents,
            "credit_used_cents": credit_used_cents,
            "credit_future_installments_cents": credit_future_cents,
            "accounts": items,
        }

    async def set_account_initial_balance(
        self, account_id: str, initial_balance_cents: int
    ) -> Account | None:
        async with self.session_factory() as session:
            acc = await session.get(Account, account_id)
            if acc is None:
                return None
            acc.initial_balance_cents = initial_balance_cents
            await session.commit()
            if self.storage is not None:
                self.storage.schedule_snapshot()
            return acc

    async def adjust_account_balance(
        self, account_id: str, target_balance_cents: int
    ) -> Account | None:
        """Ajusta o saldo inicial para que o saldo atual da conta fique exatamente igual ao desejado."""
        balances = await self.get_account_balances()
        cur_item = next((a for a in balances["accounts"] if a["id"] == account_id), None)
        if cur_item is None:
            return None
        net_movements = cur_item["incomes_cents"] - cur_item["expenses_cents"]
        new_initial = target_balance_cents - net_movements
        return await self.set_account_initial_balance(account_id, new_initial)

    async def get_active_installments(self, as_of: datetime | None = None) -> list[dict[str, Any]]:
        """Agrupa parcelamentos ativos/futuros para acompanhamento de faturas."""
        ref_now = as_of or datetime.now(UTC)
        async with self.session_factory() as session:
            rows = (
                await session.scalars(
                    select(Transaction)
                    .options(selectinload(Transaction.account), selectinload(Transaction.category))
                    .where(
                        Transaction.deleted_at.is_(None),
                        Transaction.installment_group_id.is_not(None),
                    )
                    .order_by(Transaction.occurred_at.asc())
                )
            ).all()

        groups: dict[str, list[Transaction]] = {}
        for tx in rows:
            if tx.installment_group_id:
                groups.setdefault(tx.installment_group_id, []).append(tx)

        result = []
        for gid, txs in groups.items():
            total_cents = sum(t.amount_cents for t in txs)
            future_txs = [
                t
                for t in txs
                if (t.occurred_at if t.occurred_at.tzinfo else t.occurred_at.replace(tzinfo=UTC))
                > ref_now
            ]
            remaining_cents = sum(t.amount_cents for t in future_txs)
            first = txs[0]
            base_desc = first.description.rsplit(" (", 1)[0]
            result.append(
                {
                    "installment_group_id": gid,
                    "description": base_desc,
                    "account_name": first.account.name if first.account else "",
                    "category_icon": first.category.icon if first.category else "💳",
                    "total_installments": first.installment_total or len(txs),
                    "remaining_installments": len(future_txs),
                    "total_cents": total_cents,
                    "remaining_cents": remaining_cents,
                    "installment_amount_cents": first.amount_cents,
                    "next_due_at": future_txs[0].occurred_at.isoformat() if future_txs else None,
                }
            )
        return result

    async def create_account(
        self,
        *,
        name: str,
        acc_type: str = "credit",
        color: str = "#6366f1",
        initial_balance_cents: int = 0,
        closing_day: int | None = None,
        due_day: int | None = None,
        credit_limit_cents: int = 0,
    ) -> Account:
        async with self.session_factory() as session:
            acc = Account(
                name=name.strip(),
                type=acc_type,
                color=color,
                initial_balance_cents=initial_balance_cents,
                closing_day=closing_day,
                due_day=due_day,
                credit_limit_cents=credit_limit_cents,
            )
            session.add(acc)
            await session.commit()
            await session.refresh(acc)
            if self.storage is not None:
                self.storage.schedule_snapshot()
            return acc

    async def update_account(
        self,
        account_id: str,
        *,
        name: str | None = None,
        color: str | None = None,
        closing_day: int | None = None,
        due_day: int | None = None,
        credit_limit_cents: int | None = None,
        is_active: bool | None = None,
    ) -> Account | None:
        async with self.session_factory() as session:
            acc = await session.get(Account, account_id)
            if acc is None:
                return None
            if name is not None:
                acc.name = name.strip()
            if color is not None:
                acc.color = color
            if closing_day is not None:
                acc.closing_day = closing_day
            if due_day is not None:
                acc.due_day = due_day
            if credit_limit_cents is not None:
                acc.credit_limit_cents = credit_limit_cents
            if is_active is not None:
                acc.is_active = is_active
            await session.commit()
            await session.refresh(acc)
            if self.storage is not None:
                self.storage.schedule_snapshot()
            return acc

    async def create_category(
        self,
        *,
        name: str,
        cat_type: str,
        icon: str = "📦",
        color: str = "#64748b",
        keywords: list[str] | None = None,
    ) -> Category:
        clean_kw = [k.strip().lower() for k in (keywords or []) if k.strip()]
        async with self.session_factory() as session:
            cat = Category(
                name=name.strip(),
                type=cat_type,
                icon=icon.strip() or "📦",
                color=color.strip() or "#64748b",
                keywords_json=json.dumps(clean_kw, ensure_ascii=False),
            )
            session.add(cat)
            await session.commit()
            await session.refresh(cat)
            if self.storage is not None:
                self.storage.schedule_snapshot()
            return cat

    async def update_category(
        self,
        category_id: str,
        *,
        name: str | None = None,
        icon: str | None = None,
        color: str | None = None,
        keywords: list[str] | None = None,
    ) -> Category | None:
        async with self.session_factory() as session:
            cat = await session.get(Category, category_id)
            if cat is None:
                return None
            if name is not None:
                cat.name = name.strip()
            if icon is not None:
                cat.icon = icon.strip() or cat.icon
            if color is not None:
                cat.color = color.strip() or cat.color
            if keywords is not None:
                clean_kw = [k.strip().lower() for k in keywords if k.strip()]
                cat.keywords_json = json.dumps(clean_kw, ensure_ascii=False)
            await session.commit()
            await session.refresh(cat)
            if self.storage is not None:
                self.storage.schedule_snapshot()
            return cat

    async def delete_category(self, category_id: str) -> tuple[bool, str]:
        async with self.session_factory() as session:
            cat = await session.get(Category, category_id)
            if cat is None:
                return False, "Categoria não encontrada."
            has_tx = await session.scalar(
                select(Transaction.id)
                .where(Transaction.category_id == category_id, Transaction.deleted_at.is_(None))
                .limit(1)
            )
            if has_tx is not None:
                return False, "Categoria possui lançamentos vinculados."
            budget = await session.scalar(
                select(CategoryBudget).where(CategoryBudget.category_id == category_id)
            )
            if budget is not None:
                await session.delete(budget)
            await session.delete(cat)
            await session.commit()
            if self.storage is not None:
                self.storage.schedule_snapshot()
            return True, ""

    async def get_card_invoice(
        self,
        account_id: str,
        month: str | None = None,
        *,
        as_of: datetime | None = None,
    ) -> dict[str, Any] | None:
        ref_now = as_of or datetime.now(UTC)
        async with self.session_factory() as session:
            acc = await session.get(Account, account_id)
            if acc is None or acc.type != "credit":
                return None
            target_month = month or _billing_month_for(ref_now, acc.closing_day)
            stmt = (
                select(Transaction)
                .options(
                    selectinload(Transaction.category),
                    selectinload(Transaction.account),
                )
                .where(
                    Transaction.deleted_at.is_(None),
                    (Transaction.account_id == account_id)
                    | (Transaction.transfer_to_account_id == account_id),
                )
                .order_by(Transaction.occurred_at.desc())
            )
            all_card_txs = list((await session.scalars(stmt)).all())

        invoice_txs: list[Transaction] = []
        total_cents = 0
        paid_cents = 0
        for tx in all_card_txs:
            bm = tx.billing_month or _billing_month_for(
                tx.occurred_at if tx.occurred_at.tzinfo else tx.occurred_at.replace(tzinfo=UTC),
                acc.closing_day,
            )
            if bm != target_month:
                continue
            if tx.type == "expense" and tx.account_id == account_id:
                invoice_txs.append(tx)
                total_cents += tx.amount_cents
            elif tx.type == "income" and tx.account_id == account_id:
                invoice_txs.append(tx)
                paid_cents += tx.amount_cents
            elif tx.type == "transfer" and tx.transfer_to_account_id == account_id:
                invoice_txs.append(tx)
                paid_cents += tx.amount_cents

        remaining_cents = max(0, total_cents - paid_cents)
        cur_open = _billing_month_for(ref_now, acc.closing_day)
        if total_cents > 0 and remaining_cents == 0:
            status = "paid"
        elif target_month < cur_open:
            status = "closed"
        else:
            status = "open"

        return {
            "account_id": acc.id,
            "account_name": acc.name,
            "month": target_month,
            "closing_day": acc.closing_day,
            "due_day": acc.due_day,
            "credit_limit_cents": acc.credit_limit_cents,
            "total_cents": total_cents,
            "paid_cents": paid_cents,
            "remaining_cents": remaining_cents,
            "status": status,
            "transactions": invoice_txs,
        }

    async def pay_card_invoice(
        self,
        account_id: str,
        *,
        month: str,
        from_account_id: str,
        amount_cents: int | None = None,
    ) -> Transaction | None:
        inv = await self.get_card_invoice(account_id, month)
        if inv is None:
            return None
        pay_amt = amount_cents or inv["remaining_cents"]
        if pay_amt <= 0:
            return None

        async with self.session_factory() as session:
            cat = await session.scalar(select(Category).where(Category.type == "expense").limit(1))
            if cat is None:
                return None
            cat_id = cat.id

        return await self.create_transaction(
            TransactionInput(
                tx_type="transfer",
                amount_cents=pay_amt,
                description=f"Pagamento fatura {inv['account_name']} ({month})",
                category_id=cat_id,
                account_id=from_account_id,
                transfer_to_account_id=account_id,
                occurred_at=datetime.now(UTC),
                source="web",
                billing_month=month,
            )
        )

    async def list_budgets(self, *, as_of: datetime | None = None) -> list[dict[str, Any]]:
        ref_now = as_of or datetime.now(UTC)
        month_start = ref_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_end = _add_months(month_start, 1)

        async with self.session_factory() as session:
            cats = list(
                (
                    await session.scalars(
                        select(Category).where(Category.type == "expense").order_by(Category.name)
                    )
                ).all()
            )
            budgets = list((await session.scalars(select(CategoryBudget))).all())
            txs = (
                await session.execute(
                    select(Transaction.category_id, Transaction.amount_cents).where(
                        and_(
                            Transaction.deleted_at.is_(None),
                            Transaction.type == "expense",
                            Transaction.occurred_at >= month_start,
                            Transaction.occurred_at < month_end,
                        )
                    )
                )
            ).all()

        spent_by_cat: dict[str, int] = {}
        for cid, amt in txs:
            spent_by_cat[cid] = spent_by_cat.get(cid, 0) + amt
        budget_map = {b.category_id: b.limit_cents for b in budgets}

        result: list[dict[str, Any]] = []
        for c in cats:
            limit_cents = budget_map.get(c.id, 0)
            spent_cents = spent_by_cat.get(c.id, 0)
            pct = round((spent_cents / limit_cents) * 100, 1) if limit_cents > 0 else 0.0
            status = (
                "none"
                if limit_cents <= 0
                else ("exceeded" if pct >= 100 else ("warning" if pct >= 80 else "ok"))
            )
            result.append(
                {
                    "category_id": c.id,
                    "category_name": c.name,
                    "category_icon": c.icon,
                    "category_color": c.color,
                    "limit_cents": limit_cents,
                    "spent_cents": spent_cents,
                    "remaining_cents": max(0, limit_cents - spent_cents) if limit_cents > 0 else 0,
                    "pct": pct,
                    "status": status,
                }
            )
        return result

    async def upsert_budget(self, category_id: str, limit_cents: int) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            cat = await session.get(Category, category_id)
            if cat is None:
                return None
            existing = await session.scalar(
                select(CategoryBudget).where(CategoryBudget.category_id == category_id)
            )
            if limit_cents <= 0:
                if existing is not None:
                    await session.delete(existing)
                    await session.commit()
            elif existing is not None:
                existing.limit_cents = limit_cents
                await session.commit()
            else:
                session.add(CategoryBudget(category_id=category_id, limit_cents=limit_cents))
                await session.commit()
            if self.storage is not None:
                self.storage.schedule_snapshot()
        budgets = await self.list_budgets()
        return next((b for b in budgets if b["category_id"] == category_id), None)

    async def create_recurring_bill(
        self,
        *,
        name: str,
        amount_cents: int,
        due_day: int,
        category_id: str,
        account_id: str,
        recurrence: str = "monthly",
        due_month: int | None = None,
    ) -> RecurringBill:
        async with self.session_factory() as session:
            bill = RecurringBill(
                name=name.strip(),
                amount_cents=amount_cents,
                due_day=due_day,
                due_month=due_month,
                recurrence=recurrence,
                category_id=category_id,
                account_id=account_id,
            )
            session.add(bill)
            await session.commit()
            stmt = (
                select(RecurringBill)
                .options(selectinload(RecurringBill.category), selectinload(RecurringBill.account))
                .where(RecurringBill.id == bill.id)
            )
            loaded = await session.scalar(stmt)
            assert loaded is not None
            if self.storage is not None:
                self.storage.schedule_snapshot()
            return loaded

    async def list_recurring_bills(self, as_of: datetime | None = None) -> list[dict[str, Any]]:
        ref_now = as_of or datetime.now(UTC)
        today_date = ref_now.date()
        cur_month_period = f"{ref_now.year}-{ref_now.month:02d}"
        cur_year_period = f"{ref_now.year}"

        async with self.session_factory() as session:
            bills = (
                await session.scalars(
                    select(RecurringBill)
                    .options(selectinload(RecurringBill.category), selectinload(RecurringBill.account))
                    .where(RecurringBill.is_active.is_(True))
                    .order_by(RecurringBill.due_day.asc())
                )
            ).all()

        items = []
        for b in bills:
            if b.recurrence == "yearly":
                m = b.due_month or ref_now.month
                max_d = calendar.monthrange(ref_now.year, m)[1]
                due_dt = datetime(ref_now.year, m, min(b.due_day, max_d), tzinfo=UTC)
                is_paid = b.last_paid_period == cur_year_period
            else:
                max_d = calendar.monthrange(ref_now.year, ref_now.month)[1]
                due_dt = datetime(ref_now.year, ref_now.month, min(b.due_day, max_d), tzinfo=UTC)
                is_paid = b.last_paid_period == cur_month_period

            days_diff = (due_dt.date() - today_date).days
            if is_paid:
                status = "paid"
            elif days_diff < 0:
                status = "overdue"
            elif days_diff <= 5:
                status = "due_soon"
            else:
                status = "upcoming"

            items.append(
                {
                    "id": b.id,
                    "name": b.name,
                    "amount_cents": b.amount_cents,
                    "recurrence": b.recurrence,
                    "due_day": b.due_day,
                    "due_month": b.due_month,
                    "due_date": due_dt.date().isoformat(),
                    "days_until_due": days_diff,
                    "status": status,
                    "category_id": b.category_id,
                    "category_name": b.category.name if b.category else "",
                    "category_icon": b.category.icon if b.category else "📄",
                    "account_id": b.account_id,
                    "account_name": b.account.name if b.account else "",
                    "last_paid_period": b.last_paid_period,
                }
            )
        return items

    async def pay_recurring_bill(
        self,
        bill_id: str,
        *,
        amount_cents: int | None = None,
        account_id: str | None = None,
        as_of: datetime | None = None,
    ) -> Transaction | None:
        ref_now = as_of or datetime.now(UTC)
        async with self.session_factory() as session:
            bill = await session.get(RecurringBill, bill_id)
            if bill is None or not bill.is_active:
                return None

            period_key = f"{ref_now.year}" if bill.recurrence == "yearly" else f"{ref_now.year}-{ref_now.month:02d}"
            bill.last_paid_period = period_key
            await session.commit()

            pay_amount = amount_cents if amount_cents is not None else bill.amount_cents
            pay_acc = account_id if account_id is not None else bill.account_id

        return await self.create_transaction(
            TransactionInput(
                tx_type="expense",
                amount_cents=pay_amount,
                description=f"Pagamento {bill.name}",
                category_id=bill.category_id,
                account_id=pay_acc,
                occurred_at=ref_now,
                source="recurring_bill",
            )
        )

    async def delete_recurring_bill(self, bill_id: str) -> bool:
        async with self.session_factory() as session:
            bill = await session.get(RecurringBill, bill_id)
            if bill is None:
                return False
            bill.is_active = False
            await session.commit()
            if self.storage is not None:
                self.storage.schedule_snapshot()
            return True

    async def get_upcoming_dues(
        self, days_ahead: int = 7, as_of: datetime | None = None
    ) -> list[dict[str, Any]]:
        """Retorna faturas de cartão e contas fixas vencendo em breve ou atrasadas."""
        ref_now = as_of or datetime.now(UTC)
        today_date = ref_now.date()
        dues: list[dict[str, Any]] = []

        # 1. Contas fixas pendentes
        bills = await self.list_recurring_bills(as_of=ref_now)
        for b in bills:
            if b["status"] != "paid" and b["days_until_due"] <= days_ahead:
                dues.append(
                    {
                        "kind": "bill",
                        "id": b["id"],
                        "title": f"{b['category_icon']} {b['name']}",
                        "amount_cents": b["amount_cents"],
                        "due_day": b["due_day"],
                        "days_until_due": b["days_until_due"],
                        "status": b["status"],
                    }
                )

        # 2. Cartões de crédito com vencimento próximo
        bal_data = await self.get_account_balances(as_of=ref_now)
        for acc in bal_data["accounts"]:
            if acc["type"] == "credit" and acc.get("due_day"):
                used = max(0, acc["expenses_cents"] - acc["incomes_cents"] - acc["initial_balance_cents"])
                if used <= 0:
                    continue
                max_d = calendar.monthrange(ref_now.year, ref_now.month)[1]
                due_dt = datetime(
                    ref_now.year, ref_now.month, min(acc["due_day"], max_d), tzinfo=UTC
                )
                diff = (due_dt.date() - today_date).days
                if diff <= days_ahead:
                    dues.append(
                        {
                            "kind": "credit_card",
                            "id": acc["id"],
                            "title": f"💳 Fatura {acc['name']}",
                            "amount_cents": used,
                            "due_day": acc["due_day"],
                            "days_until_due": diff,
                            "status": "overdue" if diff < 0 else "due_soon",
                        }
                    )

        dues.sort(key=lambda d: d["days_until_due"])
        return dues

    async def record_sync_state(
        self, *, pinned_msg_id: int, file_id: str, checksum_sha256: str, synced_at: datetime
    ) -> None:
        async with self.session_factory() as session:
            state = await session.get(SyncState, 1)
            if state is None:
                state = SyncState(id=1)
                session.add(state)
            state.pinned_msg_id = pinned_msg_id
            state.snapshot_file_id = file_id
            state.checksum_sha256 = checksum_sha256
            state.last_synced_at = synced_at
            await session.commit()

    async def get_sync_state(self) -> SyncState | None:
        async with self.session_factory() as session:
            return await session.get(SyncState, 1)

    @staticmethod
    async def _load_tx(session: AsyncSession, tx_id: str) -> Transaction | None:
        stmt = (
            select(Transaction)
            .options(
                selectinload(Transaction.category),
                selectinload(Transaction.account),
                selectinload(Transaction.transfer_to_account),
            )
            .where(Transaction.id == tx_id)
        )
        return await session.scalar(stmt)

    @staticmethod
    def _to_channel_payload(tx: Transaction, deleted: bool = False) -> dict[str, Any]:
        return {
            "tx_id": tx.id,
            "tx_type": tx.type,
            "amount_cents": tx.amount_cents,
            "category_name": tx.category.name,
            "account_name": tx.account.name,
            "description": tx.description,
            "occurred_at": tx.occurred_at,
            "deleted": deleted,
        }
