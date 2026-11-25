"""Parser financeiro determinístico em PT-BR (Camada 1 — < 5ms)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta


def _strip_accents(text: str) -> str:
    return (
        unicodedata.normalize("NFKD", text)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )


@dataclass(slots=True)
class CategoryMatchTarget:
    id: str
    name: str
    type: str  # expense | income
    keywords: list[str]


@dataclass(slots=True)
class AccountMatchTarget:
    id: str
    name: str
    type: str


@dataclass(slots=True)
class ParsedTransaction:
    tx_type: str  # expense | income | transfer
    amount_cents: int
    description: str
    category_id: str | None
    account_id: str | None
    occurred_at: datetime
    confidence: float
    installments_total: int = 1
    transfer_to_account_id: str | None = None
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class FinanceQuestion:
    intent: str  # balance | installments | summary_today | summary_month
    account_hint: str | None = None


_INCOME_KEYWORDS = {
    "recebi",
    "ganhei",
    "salario",
    "pagamento",
    "freela",
    "freelance",
    "reembolso",
    "estorno",
    "dividendo",
    "dividendos",
    "rendimento",
    "vendi",
    "venda",
    "pix recebido",
    "entrada",
    "cashback",
    "lucro",
    "bonus",
}

_EXPENSE_KEYWORDS = {
    "gastei",
    "paguei",
    "comprei",
    "mandei",
    "transferi",
    "saquei",
    "almoço",
    "almoco",
    "jantar",
    "uber",
    "mercado",
}

_ACCOUNT_ALIASES: dict[str, list[str]] = {
    "Cartão de Crédito": ["credito", "cartao", "nubank", "inter", "itau", "bradesco", "mastercard", "visa", "fatura"],
    "Pix": ["pix"],
    "Carteira": ["carteira", "dinheiro", "especie"],
    "Conta Principal": ["conta", "debito", "corrente", "banco", "transferencia"],
}

# Captura datas: dd/mm/yyyy ou dd/mm
_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")

# Captura parcelamentos: "6x de 100", "6x100", "em 6x", "6x", "6 parcelas", "6 vezes"
_INSTALLMENT_PER_VALUE_RE = re.compile(
    r"\b(?P<count>\d{1,2})\s*x\s*(?:de\s*)?(?:r\$\s*)?(?P<per>(?:\d{1,3}(?:\.\d{3})+|\d+)(?:[.,]\d{1,2})?)\b",
    re.IGNORECASE,
)
_INSTALLMENT_COUNT_RE = re.compile(
    r"\b(?:em\s*)?(?P<count>\d{1,2})\s*(?:x|vezes|parcelas?)\b",
    re.IGNORECASE,
)

# Captura valores monetários brasileiros ou simples, com sinal opcional (+ ou -)
# Ex: +5500, -45,90, R$ 1.250,00, 1250.50, 80 reais
_AMOUNT_RE = re.compile(
    r"(?P<sign>[+-])?\s*(?:r\$\s*)?(?P<num>(?:\d{1,3}(?:\.\d{3})+|\d+)(?:[.,]\d{1,2})?)(?:\s*(?:reais|real|r\$))?",
    re.IGNORECASE,
)


def parse_finance_question(
    raw_text: str,
    accounts: list[AccountMatchTarget] | None = None,
) -> FinanceQuestion | None:
    """Detecta perguntas em linguagem natural sobre saldo, parcelas ou resumo."""
    norm = _strip_accents(raw_text.strip())
    if not norm:
        return None

    # Se tiver número monetário claro junto com verbo de gasto, não é pergunta de saldo
    is_question_shape = (
        "?" in raw_text
        or any(
            kw in norm
            for kw in (
                "saldo",
                "quanto tenho",
                "quanto eu tenho",
                "quanto tem",
                "quanto falta",
                "parcela",
                "parcelamento",
                "fatura",
                "quanto gastei",
                "quanto ganhei",
            )
        )
    )
    if not is_question_shape:
        return None

    if any(kw in norm for kw in ("parcela", "parcelamento", "parcelado")):
        return FinanceQuestion(intent="installments")

    if any(kw in norm for kw in ("saldo", "quanto tenho", "quanto eu tenho", "quanto tem", "fatura")):
        account_hint: str | None = None
        if accounts:
            tokens = set(re.findall(r"[a-z0-9]+", norm))
            for acc in accounts:
                if _strip_accents(acc.name) in norm:
                    account_hint = acc.name
                    break
            if account_hint is None:
                for acc in accounts:
                    aliases = [a for a in _ACCOUNT_ALIASES.get(acc.name, []) if a != "conta"]
                    if any(alias in tokens for alias in aliases):
                        account_hint = acc.name
                        break
        return FinanceQuestion(intent="balance", account_hint=account_hint)

    if "quanto gastei" in norm or "quanto ganhei" in norm:
        if "hoje" in norm:
            return FinanceQuestion(intent="summary_today")
        return FinanceQuestion(intent="summary_month")

    return None


def _parse_br_number_to_cents(num_str: str) -> int:
    """Converte string numérica PT-BR/EN para centavos inteiros."""
    s = num_str.strip()
    if "," in s and "." in s:
        # Ex: 1.250,90 -> remove pontos de milhar, troca vírgula por ponto
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        # Ex: 45,90 -> troca vírgula por ponto
        s = s.replace(",", ".")
    elif "." in s:
        # Ex: 1.250 (milhar) vs 45.90 (decimal)
        parts = s.split(".")
        if len(parts[-1]) == 3 and all(p.isdigit() for p in parts):
            s = s.replace(".", "")

    value = float(s)
    return int(round(value * 100))


def parse_ptbr_transaction(
    raw_text: str,
    categories: list[CategoryMatchTarget],
    accounts: list[AccountMatchTarget],
    now: datetime | None = None,
) -> ParsedTransaction | None:
    """Interpreta texto livre em PT-BR para estruturar um lançamento financeiro."""
    text = raw_text.strip()
    if not text:
        return None

    ref_now = now or datetime.now(UTC)
    working = text

    # 0. Extrair #tags transversais (ex: #viagem, #reembolso)
    raw_tags = re.findall(r"#([a-zA-Z0-9_\-À-ÿ]+)", working)
    tags = list(dict.fromkeys(t.lower() for t in raw_tags if t.strip()))
    if tags:
        working = re.sub(r"#[a-zA-Z0-9_\-À-ÿ]+", " ", working)

    # 1. Extrair data relativa ou explícita
    occurred_at = ref_now
    norm_full = _strip_accents(working)

    if re.search(r"\banteontem\b", norm_full):
        occurred_at = ref_now - timedelta(days=2)
        working = re.sub(r"\banteontem\b", " ", working, flags=re.IGNORECASE)
    elif re.search(r"\bontem\b", norm_full):
        occurred_at = ref_now - timedelta(days=1)
        working = re.sub(r"\bontem\b", " ", working, flags=re.IGNORECASE)
    elif re.search(r"\bhoje\b", norm_full):
        working = re.sub(r"\bhoje\b", " ", working, flags=re.IGNORECASE)
    else:
        date_match = _DATE_RE.search(working)
        if date_match:
            day = int(date_match.group(1))
            month = int(date_match.group(2))
            year_raw = date_match.group(3)
            year = ref_now.year if not year_raw else (2000 + int(year_raw) if len(year_raw) == 2 else int(year_raw))
            try:
                occurred_at = ref_now.replace(year=year, month=month, day=day)
                working = working[: date_match.start()] + " " + working[date_match.end() :]
            except ValueError:
                pass

    # 1.5. Extrair parcelamento (ex: "6x de 100" ou "em 6x")
    installments_total = 1
    forced_amount_cents: int | None = None
    inst_per = _INSTALLMENT_PER_VALUE_RE.search(working)
    if inst_per:
        cnt = int(inst_per.group("count"))
        per_cents = _parse_br_number_to_cents(inst_per.group("per"))
        if 2 <= cnt <= 48 and per_cents > 0:
            installments_total = cnt
            forced_amount_cents = cnt * per_cents
            working = working[: inst_per.start()] + " " + working[inst_per.end() :]
    else:
        inst_cnt = _INSTALLMENT_COUNT_RE.search(working)
        if inst_cnt:
            cnt = int(inst_cnt.group("count"))
            if 2 <= cnt <= 48:
                installments_total = cnt
                working = working[: inst_cnt.start()] + " " + working[inst_cnt.end() :]

    # 2. Extrair valor monetário (primeiro match válido > 0)
    amount_cents = 0
    explicit_sign: str | None = None
    amount_span: tuple[int, int] | None = None

    if forced_amount_cents is not None:
        amount_cents = forced_amount_cents
        desc_candidate = working.strip()
        amount_span = (0, 0)
    else:
        for m in _AMOUNT_RE.finditer(working):
            candidate_cents = _parse_br_number_to_cents(m.group("num"))
            if candidate_cents > 0:
                amount_cents = candidate_cents
                explicit_sign = m.group("sign")
                amount_span = (m.start(), m.end())
                break

        if amount_cents <= 0 or amount_span is None:
            return None

        # Remove o valor do texto restante para limpar descrição
        desc_candidate = (working[: amount_span[0]] + " " + working[amount_span[1] :]).strip()

    norm_desc = _strip_accents(desc_candidate)
    tokens = set(re.findall(r"[a-z0-9]+", norm_desc))

    # 3. Determinar tipo (transfer | income | expense)
    is_transfer = any(
        kw in norm_desc
        for kw in ("transferi", "transferir", "transferencia", "paguei fatura", "pagar fatura")
    )
    transfer_to_account_id: str | None = None

    if is_transfer:
        tx_type = "transfer"
    elif explicit_sign == "+":
        tx_type = "income"
    elif explicit_sign == "-":
        tx_type = "expense"
    elif any(kw in norm_desc for kw in _INCOME_KEYWORDS):
        tx_type = "income"
    elif any(kw in norm_desc for kw in _EXPENSE_KEYWORDS):
        tx_type = "expense"
    else:
        tx_type = "expense"

    # 4. Identificar conta (e conta destino se for transferência)
    def _match_accounts_in_text(segment: str) -> str | None:
        seg_tokens = set(re.findall(r"[a-z0-9]+", segment))
        for acc in accounts:
            if _strip_accents(acc.name) in segment:
                return acc.id
        for acc in accounts:
            aliases = _ACCOUNT_ALIASES.get(acc.name, [])
            if any(alias in seg_tokens for alias in aliases):
                return acc.id
        return None

    matched_account_id: str | None = None
    if tx_type == "transfer":
        if " para " in norm_desc:
            left_part, _, right_part = norm_desc.partition(" para ")
            matched_account_id = _match_accounts_in_text(left_part)
            transfer_to_account_id = _match_accounts_in_text(right_part)
        elif "fatura" in norm_desc:
            credit_acc = next((a for a in accounts if a.type == "credit"), None)
            checking_acc = next((a for a in accounts if a.type == "checking"), None)
            matched_account_id = _match_accounts_in_text(norm_desc) or (checking_acc.id if checking_acc else None)
            transfer_to_account_id = credit_acc.id if credit_acc else None
            if matched_account_id == transfer_to_account_id and checking_acc:
                matched_account_id = checking_acc.id
        if matched_account_id is None and accounts:
            matched_account_id = accounts[0].id
        if transfer_to_account_id is None and len(accounts) > 1:
            transfer_to_account_id = next((a.id for a in accounts if a.id != matched_account_id), None)
    else:
        matched_account_id = _match_accounts_in_text(norm_desc)
        if matched_account_id is None and installments_total > 1:
            credit_acc = next((a for a in accounts if a.type == "credit"), None)
            if credit_acc is not None:
                matched_account_id = credit_acc.id
        if matched_account_id is None and accounts:
            matched_account_id = accounts[0].id

    # 5. Identificar categoria do tipo compatível
    cat_lookup_type = "expense" if tx_type == "transfer" else tx_type
    typed_categories = [c for c in categories if c.type == cat_lookup_type]
    matched_category_id: str | None = None
    best_score = 0

    for cat in typed_categories:
        score = 0
        cat_norm = _strip_accents(cat.name)
        if cat_norm in norm_desc:
            score += 3
        for kw in cat.keywords:
            kw_norm = _strip_accents(kw)
            if kw_norm in tokens:
                score += 2
            elif len(kw_norm) >= 4 and kw_norm in norm_desc:
                score += 1
        if score > best_score:
            best_score = score
            matched_category_id = cat.id

    if matched_category_id is None and typed_categories:
        fallback = next(
            (c for c in typed_categories if c.name in ("Outros", "Outras Receitas")),
            typed_categories[-1],
        )
        matched_category_id = fallback.id

    # 6. Limpar preposições iniciais soltas na descrição
    cleaned_desc = re.sub(r"\s+", " ", desc_candidate).strip(" -.,;:")
    cleaned_desc = re.sub(
        r"^(?:no|na|nos|nas|em|de|do|da|com|para|pra|por)\s+",
        "",
        cleaned_desc,
        flags=re.IGNORECASE,
    ).strip()
    if not cleaned_desc:
        cleaned_desc = "Transferência entre contas" if tx_type == "transfer" else "Lançamento via Telegram"
    else:
        cleaned_desc = cleaned_desc[0].upper() + cleaned_desc[1:]

    confidence = 0.9 if best_score >= 2 else 0.7
    return ParsedTransaction(
        tx_type=tx_type,
        amount_cents=amount_cents,
        description=cleaned_desc[:250],
        category_id=matched_category_id,
        account_id=matched_account_id,
        occurred_at=occurred_at,
        confidence=confidence,
        installments_total=installments_total,
        transfer_to_account_id=transfer_to_account_id,
        tags=tags,
    )

