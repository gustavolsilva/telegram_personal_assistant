"""Testes da normalização PT-BR e registro por voz no bot e na API."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app import create_app
from core.config import get_settings
from core.database import DatabaseManager
from core.voice import VoiceTranscriptionError, normalize_spoken_ptbr, transcribe_audio
from fastapi.testclient import TestClient
from modules.finance.handlers import FinanceModule
from modules.finance.seed import seed_defaults
from modules.finance.service import FinanceService


def test_normalize_spoken_ptbr() -> None:
    assert normalize_spoken_ptbr("45 reais e 90 centavos almoço nubank") == "45,90 almoço nubank"
    assert normalize_spoken_ptbr("paguei 120 reais luz pix") == "paguei 120 luz pix"
    assert normalize_spoken_ptbr("uber 23 e 50") == "uber 23,50"
    assert normalize_spoken_ptbr("45,90 almoço nubank") == "45,90 almoço nubank"


@pytest.mark.asyncio
async def test_transcribe_audio_requires_key() -> None:
    with pytest.raises(VoiceTranscriptionError):
        await transcribe_audio(b"fake-ogg")


@pytest.mark.asyncio
async def test_finance_module_handles_voice_bytes(tmp_path) -> None:
    db = DatabaseManager(f"sqlite+aiosqlite:///{tmp_path / 'voice.db'}")
    await db.create_tables()
    try:
        async with db.session_factory() as session:
            await seed_defaults(session)

        service = FinanceService(db.session_factory)
        mod = FinanceModule(service=service)

        fake_msg = SimpleNamespace(
            message_id=77,
            voice=SimpleNamespace(mime_type="audio/ogg"),
            audio=None,
            reply_html=AsyncMock(),
        )
        fake_update = SimpleNamespace(effective_message=fake_msg)
        fake_context = SimpleNamespace(user_data={"_pending_voice_bytes": b"ogg-bytes"})

        handled = await mod.handle_text("45,90 almoço nubank", fake_update, fake_context)
        assert handled is True
        fake_msg.reply_html.assert_awaited_once()

        txs = await service.list_transactions()
        assert len(txs) == 1
        assert txs[0].amount_cents == 4590
        assert txs[0].source == "telegram_voice"
        assert "_pending_voice_bytes" not in fake_context.user_data
    finally:
        await db.dispose()


def test_chat_endpoint_accepts_spoken_ptbr(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'chat_voice.db'}")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("WEB_ACCESS_TOKEN", "")
    get_settings.cache_clear()
    try:
        app = create_app()
        with TestClient(app) as client:
            res = client.post(
                "/api/finance/chat",
                json={"message": "45 reais e 90 centavos almoço nubank"},
            )
            assert res.status_code == 200
            assert res.json()["refresh"] is True

            txs = client.get("/api/finance/transactions").json()
            assert len(txs) == 1
            assert txs[0]["amount_cents"] == 4590
    finally:
        get_settings.cache_clear()
