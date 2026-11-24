"""Seed idempotente de categorias e contas padrão brasileiras."""

from __future__ import annotations

import json

from modules.finance.models import Account, Category
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_ACCOUNTS = [
    {"name": "Conta Principal", "type": "checking", "color": "#6366f1"},
    {"name": "Cartão de Crédito", "type": "credit", "color": "#8b5cf6"},
    {"name": "Pix", "type": "checking", "color": "#14b8a6"},
    {"name": "Carteira", "type": "wallet", "color": "#f59e0b"},
]

DEFAULT_CATEGORIES = [
    # Despesas
    {
        "name": "Alimentação",
        "type": "expense",
        "icon": "🍽️",
        "color": "#ef4444",
        "keywords": ["almoco", "almoço", "jantar", "lanche", "ifood", "restaurante", "cafe", "café", "padaria", "pizza", "hamburguer", "sushi", "bar", "cerveja"],
    },
    {
        "name": "Mercado",
        "type": "expense",
        "icon": "🛒",
        "color": "#f97316",
        "keywords": ["mercado", "supermercado", "hortifruti", "acougue", "açougue", "feira", "carrefour", "atacadao", "atacadão", "assai", "assaí", "compras"],
    },
    {
        "name": "Transporte",
        "type": "expense",
        "icon": "🚗",
        "color": "#eab308",
        "keywords": ["uber", "99", "taxi", "táxi", "gasolina", "etanol", "combustivel", "combustível", "posto", "estacionamento", "pedagio", "pedágio", "onibus", "ônibus", "metro", "metrô", "passagem"],
    },
    {
        "name": "Moradia",
        "type": "expense",
        "icon": "🏠",
        "color": "#3b82f6",
        "keywords": [
            "aluguel", "condominio", "condomínio", "luz", "energia", "eletrica", "elétrica",
            "enel", "cemig", "cpfl", "light", "agua", "água", "saneamento", "sabesp", "copasa",
            "cedae", "gas", "gás", "internet", "internet fixa", "fibra", "iptu", "financiamento",
            "imovel", "imóvel", "prestacao", "prestação", "reforma", "manutencao", "manutenção",
        ],
    },
    {
        "name": "Veículo",
        "type": "expense",
        "icon": "🚙",
        "color": "#0284c7",
        "keywords": [
            "ipva", "licenciamento", "multa", "multas", "detran", "dpvat", "seguro auto",
            "mecanico", "mecânico", "revisao", "revisão", "pneu", "oleo", "óleo", "lavagem",
            "veiculo", "veículo", "carro", "moto",
        ],
    },
    {
        "name": "Saúde",
        "type": "expense",
        "icon": "🩺",
        "color": "#ec4899",
        "keywords": ["farmacia", "farmácia", "remedio", "remédio", "medico", "médico", "consulta", "exame", "dentista", "academia", "plano de saude", "psicologo"],
    },
    {
        "name": "Lazer",
        "type": "expense",
        "icon": "🎮",
        "color": "#a855f7",
        "keywords": ["cinema", "show", "viagem", "hotel", "jogo", "steam", "ingresso", "passeio", "parque", "lazer"],
    },
    {
        "name": "Assinaturas",
        "type": "expense",
        "icon": "📱",
        "color": "#06b6d4",
        "keywords": [
            "netflix", "spotify", "amazon", "prime", "youtube", "icloud", "chatgpt",
            "assinatura", "celular", "internet movel", "internet móvel", "plano movel",
            "claro", "vivo", "tim",
        ],
    },
    {
        "name": "Educação",
        "type": "expense",
        "icon": "📚",
        "color": "#0ea5e9",
        "keywords": ["curso", "livro", "faculdade", "escola", "mensalidade", "ingles", "inglês", "udemy"],
    },
    {
        "name": "Vestuário",
        "type": "expense",
        "icon": "👕",
        "color": "#d946ef",
        "keywords": ["roupa", "tenis", "tênis", "sapato", "camisa", "calca", "calça", "shopping", "loja"],
    },
    {
        "name": "Outros",
        "type": "expense",
        "icon": "📦",
        "color": "#64748b",
        "keywords": ["presente", "taxa", "imposto", "doacao", "doação", "outros"],
    },
    # Receitas
    {
        "name": "Salário",
        "type": "income",
        "icon": "💼",
        "color": "#22c55e",
        "keywords": ["salario", "salário", "pagamento", "holerite", "adiantamento", "13o", "ferias", "férias"],
    },
    {
        "name": "Freelance",
        "type": "income",
        "icon": "💻",
        "color": "#10b981",
        "keywords": ["freela", "freelance", "projeto", "servico", "serviço", "consultoria", "bico"],
    },
    {
        "name": "Investimentos",
        "type": "income",
        "icon": "📈",
        "color": "#14b8a6",
        "keywords": ["dividendo", "dividendos", "rendimento", "juros", "cdb", "fii", "resgate", "lucro"],
    },
    {
        "name": "Reembolso",
        "type": "income",
        "icon": "↩️",
        "color": "#84cc16",
        "keywords": ["reembolso", "estorno", "devolucao", "devolução", "cashback"],
    },
    {
        "name": "Outras Receitas",
        "type": "income",
        "icon": "💰",
        "color": "#16a34a",
        "keywords": ["venda", "presente", "pix recebido", "ganho", "extra"],
    },
]


async def seed_defaults(session: AsyncSession) -> None:
    """Insere contas e categorias padrão caso ainda não existam."""
    existing_accounts = set((await session.scalars(select(Account.name))).all())
    for acc in DEFAULT_ACCOUNTS:
        if acc["name"] not in existing_accounts:
            session.add(Account(**acc))

    existing_cats = set(
        (await session.execute(select(Category.name, Category.type))).all()
    )
    for cat in DEFAULT_CATEGORIES:
        key = (cat["name"], cat["type"])
        if key not in existing_cats:
            session.add(
                Category(
                    name=cat["name"],
                    type=cat["type"],
                    icon=cat["icon"],
                    color=cat["color"],
                    keywords_json=json.dumps(cat["keywords"], ensure_ascii=False),
                )
            )

    await session.commit()

