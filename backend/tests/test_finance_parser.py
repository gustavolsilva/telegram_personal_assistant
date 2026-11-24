"""Bateria de testes do Parser Financeiro PT-BR."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from modules.finance.parser import (
    AccountMatchTarget,
    CategoryMatchTarget,
    parse_ptbr_transaction,
)
from modules.finance.seed import DEFAULT_ACCOUNTS, DEFAULT_CATEGORIES

CATEGORIES = [
    CategoryMatchTarget(
        id=f"cat_{i}",
        name=c["name"],
        type=c["type"],
        keywords=c["keywords"],
    )
    for i, c in enumerate(DEFAULT_CATEGORIES)
]

ACCOUNTS = [
    AccountMatchTarget(id=f"acc_{i}", name=a["name"], type=a["type"])
    for i, a in enumerate(DEFAULT_ACCOUNTS)
]

REF_NOW = datetime(2026, 11, 23, 14, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("text", "expected_type", "expected_cents", "expected_cat", "expected_acc"),
    [
        ("45,90 almoço nubank", "expense", 4590, "Alimentação", "Cartão de Crédito"),
        ("R$ 1.250,00 aluguel pix", "expense", 125000, "Moradia", "Pix"),
        ("uber 23.50", "expense", 2350, "Transporte", "Conta Principal"),
        ("mercado 189,40 ontem carteira", "expense", 18940, "Mercado", "Carteira"),
        ("+5500 salário", "income", 550000, "Salário", "Conta Principal"),
        ("recebi 450 freela pix", "income", 45000, "Freelance", "Pix"),
        ("ganhei 120 reembolso", "income", 12000, "Reembolso", "Conta Principal"),
        ("-80 farmácia", "expense", 8000, "Saúde", "Conta Principal"),
        ("netflix 55,90 cartão", "expense", 5590, "Assinaturas", "Cartão de Crédito"),
        ("curso python 99,90 15/11", "expense", 9990, "Educação", "Conta Principal"),
    ],
)
def test_parse_ptbr_transactions(
    text: str,
    expected_type: str,
    expected_cents: int,
    expected_cat: str,
    expected_acc: str,
) -> None:
    parsed = parse_ptbr_transaction(text, CATEGORIES, ACCOUNTS, now=REF_NOW)
    assert parsed is not None
    assert parsed.tx_type == expected_type
    assert parsed.amount_cents == expected_cents

    cat_name = next(c.name for c in CATEGORIES if c.id == parsed.category_id)
    acc_name = next(a.name for a in ACCOUNTS if a.id == parsed.account_id)
    assert cat_name == expected_cat
    assert acc_name == expected_acc


def test_parse_relative_and_explicit_dates() -> None:
    p_ontem = parse_ptbr_transaction("30 café ontem", CATEGORIES, ACCOUNTS, now=REF_NOW)
    assert p_ontem is not None
    assert p_ontem.occurred_at.day == 22

    p_explicit = parse_ptbr_transaction("120 cinema 10/11", CATEGORIES, ACCOUNTS, now=REF_NOW)
    assert p_explicit is not None
    assert (p_explicit.occurred_at.day, p_explicit.occurred_at.month) == (10, 11)


def test_parse_invalid_without_amount_returns_none() -> None:
    assert parse_ptbr_transaction("bom dia assistente", CATEGORIES, ACCOUNTS, now=REF_NOW) is None

