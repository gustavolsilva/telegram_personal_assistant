"""Parser de extratos bancários OFX e CSV brasileiros sem dependências externas."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(slots=True)
class ImportedRow:
    fitid: str
    occurred_at: datetime
    tx_type: str  # expense | income
    amount_cents: int
    description: str


def _parse_amount_to_signed_cents(raw: str) -> int:
    s = raw.strip().replace("R$", "").replace(" ", "")
    if not s:
        return 0
    neg = s.startswith("-") or (s.startswith("(") and s.endswith(")"))
    s = s.strip("()-+")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(".", "").replace(",", ".")
    val = round(float(s) * 100)
    return -abs(val) if neg else abs(val)


def _parse_date(raw: str) -> datetime:
    s = raw.strip()
    # OFX: 20261125120000[-3:BRT] ou 20261125
    m_ofx = re.match(r"^(\d{4})(\d{2})(\d{2})", s)
    if m_ofx and ("-" not in s and "/" not in s):
        return datetime(
            int(m_ofx.group(1)), int(m_ofx.group(2)), int(m_ofx.group(3)), 12, 0, tzinfo=UTC
        )
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%y"):
        try:
            dt = datetime.strptime(s[:10], fmt)
            return dt.replace(hour=12, tzinfo=UTC)
        except ValueError:
            continue
    return datetime.now(UTC)


def _make_fitid(occ: datetime, signed_cents: int, desc: str) -> str:
    raw = f"{occ.date().isoformat()}|{signed_cents}|{desc.strip().lower()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def parse_ofx_text(content: str) -> list[ImportedRow]:
    blocks = re.findall(r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>)|</BANKTRANLIST>)", content, re.S | re.I)
    rows: list[ImportedRow] = []
    for blk in blocks:
        def _tag(name: str, block: str = blk) -> str:
            m = re.search(rf"<{name}>\s*([^<\r\n]+)", block, re.I)
            return m.group(1).strip() if m else ""

        amt_raw = _tag("TRNAMT")
        dt_raw = _tag("DTPOSTED")
        memo = _tag("MEMO") or _tag("NAME") or "Lançamento OFX"
        fitid = _tag("FITID")
        if not amt_raw or not dt_raw:
            continue
        signed_cents = _parse_amount_to_signed_cents(amt_raw)
        if signed_cents == 0:
            continue
        occ = _parse_date(dt_raw)
        tx_type = "income" if signed_cents > 0 else "expense"
        rows.append(
            ImportedRow(
                fitid=fitid or _make_fitid(occ, signed_cents, memo),
                occurred_at=occ,
                tx_type=tx_type,
                amount_cents=abs(signed_cents),
                description=memo[:255],
            )
        )
    return rows


def parse_csv_text(content: str) -> list[ImportedRow]:
    sample = content[:2048]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")), delimiter=delimiter)
    if not reader.fieldnames:
        return []

    norm_fields = {f.strip().lower(): f for f in reader.fieldnames if f}
    date_col = next(
        (norm_fields[k] for k in norm_fields if any(x in k for x in ("data", "date", "dt"))),
        None,
    )
    desc_col = next(
        (
            norm_fields[k]
            for k in norm_fields
            if any(x in k for x in ("descr", "title", "hist", "lanc", "lanç", "memo", "estab"))
        ),
        None,
    )
    amt_col = next(
        (norm_fields[k] for k in norm_fields if any(x in k for x in ("valor", "amount", "val"))),
        None,
    )
    if not (date_col and desc_col and amt_col):
        return []

    rows: list[ImportedRow] = []
    for rec in reader:
        dt_raw = (rec.get(date_col) or "").strip()
        desc = (rec.get(desc_col) or "").strip()
        amt_raw = (rec.get(amt_col) or "").strip()
        if not (dt_raw and desc and amt_raw):
            continue
        try:
            signed_cents = _parse_amount_to_signed_cents(amt_raw)
        except ValueError:
            continue
        if signed_cents == 0:
            continue
        occ = _parse_date(dt_raw)
        tx_type = "income" if signed_cents > 0 else "expense"
        rows.append(
            ImportedRow(
                fitid=_make_fitid(occ, signed_cents, desc),
                occurred_at=occ,
                tx_type=tx_type,
                amount_cents=abs(signed_cents),
                description=desc[:255],
            )
        )
    return rows


def parse_statement_text(filename: str, content: str) -> list[ImportedRow]:
    lower = filename.lower().strip()
    if lower.endswith(".ofx") or "<OFX>" in content.upper() or "<STMTTRN>" in content.upper():
        return parse_ofx_text(content)
    return parse_csv_text(content)
