"""Modelos ORM do Módulo Financeiro (valores em centavos e soft delete)."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime

from core.database import Base
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship


def generate_uuid7() -> str:
    """Gera UUIDv7 ordenável por tempo (RFC 9562) compatível com Python 3.12+."""
    timestamp_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand_a = int.from_bytes(os.urandom(2), "big") & 0x0FFF
    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)

    value = (timestamp_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0x2 << 62) | rand_b
    raw = value.to_bytes(16, "big")
    hx = raw.hex()
    return f"{hx[0:8]}-{hx[8:12]}-{hx[12:16]}-{hx[16:20]}-{hx[20:32]}"


def utc_now() -> datetime:
    return datetime.now(UTC)


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid7)
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="checking"
    )  # checking | credit | wallet | savings
    initial_balance_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    closing_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    due_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    credit_limit_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    color: Mapped[str] = mapped_column(String(16), nullable=False, default="#6366f1")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="account",
        foreign_keys="Transaction.account_id",
    )


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid7)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)  # expense | income
    icon: Mapped[str] = mapped_column(String(16), nullable=False, default="📦")
    color: Mapped[str] = mapped_column(String(16), nullable=False, default="#64748b")
    keywords_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    transactions: Mapped[list[Transaction]] = relationship(back_populates="category")

    __table_args__ = (Index("ix_categories_name_type", "name", "type", unique=True),)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid7)
    type: Mapped[str] = mapped_column(String(16), nullable=False)  # expense | income | transfer
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="BRL")
    description: Mapped[str] = mapped_column(String(255), nullable=False)

    category_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("categories.id"), nullable=False
    )
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id"), nullable=False
    )
    transfer_to_account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("accounts.id"), nullable=True
    )

    installment_group_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    installment_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    installment_total: Mapped[int | None] = mapped_column(Integer, nullable=True)

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    is_paid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    billing_month: Mapped[str | None] = mapped_column(String(7), nullable=True)
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="telegram_text"
    )  # telegram_text | telegram_voice | telegram_photo | web

    source_msg_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channel_msg_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    receipt_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    receipt_file_unique_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    category: Mapped[Category] = relationship(back_populates="transactions")
    account: Mapped[Account] = relationship(
        back_populates="transactions",
        foreign_keys=[account_id],
    )
    transfer_to_account: Mapped[Account | None] = relationship(
        foreign_keys=[transfer_to_account_id],
    )

    __table_args__ = (
        Index("ix_transactions_occurred_at", "occurred_at"),
        Index("ix_transactions_type_deleted", "type", "deleted_at"),
        Index("ix_transactions_installment_group", "installment_group_id"),
    )


class RecurringBill(Base):
    __tablename__ = "recurring_bills"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid7)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    recurrence: Mapped[str] = mapped_column(
        String(16), nullable=False, default="monthly"
    )  # monthly | yearly
    due_day: Mapped[int] = mapped_column(Integer, nullable=False)
    due_month: Mapped[int | None] = mapped_column(Integer, nullable=True)  # usado em yearly (ex: IPVA)
    category_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("categories.id"), nullable=False
    )
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id"), nullable=False
    )
    last_paid_period: Mapped[str | None] = mapped_column(String(16), nullable=True)  # "YYYY-MM" ou "YYYY"
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    category: Mapped[Category] = relationship()
    account: Mapped[Account] = relationship()


class CategoryBudget(Base):
    __tablename__ = "budgets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid7)
    category_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("categories.id"), nullable=False, unique=True
    )
    limit_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    category: Mapped[Category] = relationship()


class SyncState(Base):
    __tablename__ = "sync_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    pinned_msg_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snapshot_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

