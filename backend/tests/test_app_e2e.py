"""Teste ponta a ponta da aplicação FastAPI + PWA estático."""

from __future__ import annotations

from app import create_app
from fastapi.testclient import TestClient


def test_app_serves_health_and_pwa_and_finance_api(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'e2e.db'}")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    from core.config import get_settings

    get_settings.cache_clear()
    try:
        app = create_app()
        with TestClient(app) as client:
            health = client.get("/api/health")
            assert health.status_code == 200
            assert health.json()["status"] == "ok"

            index = client.get("/")
            assert index.status_code == 200
            assert "Finanças AI" in index.text

            cats = client.get("/api/finance/categories")
            assert cats.status_code == 200
            assert len(cats.json()) == 16

            summary = client.get("/api/finance/summary")
            assert summary.status_code == 200
            assert "balance_cents" in summary.json()

            chat_add = client.post("/api/finance/chat", json={"message": "45 almoço pix"})
            assert chat_add.status_code == 200
            assert chat_add.json()["refresh"] is True

            chat_bal = client.post("/api/finance/chat", json={"message": "Qual meu saldo?"})
            assert chat_bal.status_code == 200
            assert "Saldos em Contas" in chat_bal.json()["reply"]
    finally:
        get_settings.cache_clear()

