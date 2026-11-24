"""Testes da camada Vercel Serverless: normalização Neon Postgres e Telegram Webhook."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from app import create_app
from core.config import get_settings
from core.database import normalize_database_url
from fastapi.testclient import TestClient


def test_normalize_neon_and_postgres_urls() -> None:
    sqlite_url, sqlite_args = normalize_database_url("sqlite+aiosqlite:///./data/assistant.db")
    assert sqlite_url == "sqlite+aiosqlite:///./data/assistant.db"
    assert sqlite_args == {}

    neon_raw = "postgresql://user:pass@ep-cool-123.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
    norm_url, conn_args = normalize_database_url(neon_raw)
    assert norm_url == "postgresql+asyncpg://user:pass@ep-cool-123.us-east-2.aws.neon.tech/neondb"
    assert conn_args == {"ssl": "require"}

    legacy_raw = "postgres://user:pass@host:5432/db"
    norm_legacy, _ = normalize_database_url(legacy_raw)
    assert norm_legacy.startswith("postgresql+asyncpg://")


def test_telegram_webhook_secret_and_update_processing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'webhook.db'}")
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST_TOKEN")
    monkeypatch.setenv("TELEGRAM_USER_ID", "999111")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "segredo-webhook-123")
    monkeypatch.setenv("SYNC_ENABLED", "false")

    get_settings.cache_clear()
    try:
        app = create_app()
        with (
            patch("telegram.ext.Application.initialize", new=AsyncMock()),
            patch("telegram.ext.Application.process_update", new=AsyncMock()) as mock_process,
            TestClient(app) as client,
        ):
            health = client.get("/api/health")
            assert health.status_code == 200
            assert health.json()["mode"] == "vercel"

            # Secret inválido deve retornar 403
            bad_res = client.post(
                "/api/telegram/webhook",
                headers={"X-Telegram-Bot-Api-Secret-Token": "errado"},
                json={"update_id": 1},
            )
            assert bad_res.status_code == 403

            # Secret válido processa o update
            ok_res = client.post(
                "/api/telegram/webhook",
                headers={"X-Telegram-Bot-Api-Secret-Token": "segredo-webhook-123"},
                json={
                    "update_id": 2,
                    "message": {
                        "message_id": 10,
                        "date": 1700000000,
                        "chat": {"id": 999111, "type": "private"},
                        "from": {"id": 999111, "is_bot": False, "first_name": "Gustavo"},
                        "text": "45,90 almoço pix",
                    },
                },
            )
            assert ok_res.status_code == 200
            assert ok_res.json() == {"ok": True}
            mock_process.assert_awaited_once()
    finally:
        get_settings.cache_clear()
