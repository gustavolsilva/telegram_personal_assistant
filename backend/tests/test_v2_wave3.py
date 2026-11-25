"""Testes da Onda 3: OCR de comprovante por foto, importação OFX/CSV e cron diário."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app import create_app
from core.config import get_settings
from core.database import DatabaseManager
from core.voice import VoiceTranscriptionError, extract_receipt_command
from fastapi.testclient import TestClient
from modules.finance.handlers import FinanceModule
from modules.finance.importer import parse_statement_text
from modules.finance.seed import seed_defaults
from modules.finance.service import FinanceService


def test_parse_ofx_and_csv_statements() -> None:
    ofx = """<OFX><BANKMSGSRSV1><STMTTRN>
    <TRNTYPE>DEBIT<DTPOSTED>20261120120000<TRNAMT>-45.90<FITID>FIT001<MEMO>ALMOCO PADARIA
    </STMTTRN><STMTTRN>
    <TRNTYPE>CREDIT<DTPOSTED>20261121120000<TRNAMT>1200.00<FITID>FIT002<MEMO>PIX RECEBIDO FREELA
    </STMTTRN></BANKMSGSRSV1></OFX>"""
    rows = parse_statement_text("extrato.ofx", ofx)
    assert len(rows) == 2
    assert rows[0].tx_type == "expense"
    assert rows[0].amount_cents == 4590
    assert rows[0].fitid == "FIT001"
    assert rows[1].tx_type == "income"
    assert rows[1].amount_cents == 120_000

    csv_br = "Data;Descrição;Valor\n22/11/2026;Uber;-23,50\n23/11/2026;Salário;5.500,00\n"
    c_rows = parse_statement_text("nubank.csv", csv_br)
    assert len(c_rows) == 2
    assert c_rows[0].amount_cents == 2350
    assert c_rows[1].tx_type == "income"
    assert c_rows[1].amount_cents == 550_000


@pytest.mark.asyncio
async def test_receipt_ocr_requires_gemini_key() -> None:
    with pytest.raises(VoiceTranscriptionError):
        await extract_receipt_command(b"fake-jpg")


@pytest.mark.asyncio
async def test_finance_module_handles_photo_bytes(tmp_path) -> None:
    db = DatabaseManager(f"sqlite+aiosqlite:///{tmp_path / 'photo.db'}")
    await db.create_tables()
    try:
        async with db.session_factory() as session:
            await seed_defaults(session)

        service = FinanceService(db.session_factory)
        mod = FinanceModule(service=service)

        fake_msg = SimpleNamespace(
            message_id=88,
            voice=None,
            audio=None,
            photo=[SimpleNamespace(file_id="p1")],
            reply_html=AsyncMock(),
        )
        fake_update = SimpleNamespace(effective_message=fake_msg)
        fake_context = SimpleNamespace(user_data={"_pending_photo_bytes": b"jpg-bytes"})

        handled = await mod.handle_text("45,90 padaria pix", fake_update, fake_context)
        assert handled is True
        txs = await service.list_transactions()
        assert len(txs) == 1
        assert txs[0].source == "telegram_photo"
        assert txs[0].amount_cents == 4590
    finally:
        await db.dispose()


def test_import_api_deduplication_and_cron_auth(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'wave3.db'}")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("WEB_ACCESS_TOKEN", "")
    monkeypatch.setenv("CRON_SECRET", "segredo-cron")
    get_settings.cache_clear()
    try:
        app = create_app()
        with TestClient(app) as client:
            acc = client.get("/api/finance/accounts").json()[0]
            csv_txt = "Data,Title,Amount\n2026-11-20,Mercado,-120.50\n"
            prev1 = client.post(
                "/api/finance/import/preview",
                json={"account_id": acc["id"], "filename": "f.csv", "content_text": csv_txt},
            ).json()
            assert len(prev1) == 1
            assert prev1[0]["is_duplicate"] is False

            conf = client.post(
                "/api/finance/import/confirm",
                json={"account_id": acc["id"], "items": prev1},
            )
            assert conf.status_code == 200
            assert conf.json()["imported"] == 1

            # Reimportar o mesmo arquivo deve marcar duplicata
            prev2 = client.post(
                "/api/finance/import/preview",
                json={"account_id": acc["id"], "filename": "f.csv", "content_text": csv_txt},
            ).json()
            assert prev2[0]["is_duplicate"] is True

            # Cron protegido por CRON_SECRET
            assert client.get("/api/cron/daily-digest").status_code == 403
            ok_cron = client.get(
                "/api/cron/daily-digest",
                headers={"Authorization": "Bearer segredo-cron"},
            )
            assert ok_cron.status_code == 200
    finally:
        get_settings.cache_clear()
