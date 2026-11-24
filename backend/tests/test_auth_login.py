"""Testes da tela de Login, sessão HMAC e proteção das rotas quando WEB_ACCESS_TOKEN está ativo."""

from __future__ import annotations

from app import create_app
from core.config import get_settings
from fastapi.testclient import TestClient


def test_login_and_protected_api(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("WEB_ACCESS_USER", "gustavo")
    monkeypatch.setenv("WEB_ACCESS_TOKEN", "minha-senha-forte")

    get_settings.cache_clear()
    try:
        app = create_app()
        with TestClient(app) as client:
            # 1. Sem login: status indica auth_required=True, authenticated=False
            st = client.get("/api/auth/status").json()
            assert st["auth_required"] is True
            assert st["authenticated"] is False
            assert st["username_required"] is True

            # 2. Rotas financeiras devem retornar 401 sem autenticação
            assert client.get("/api/finance/summary").status_code == 401

            # 3. Senha incorreta retorna 401
            bad = client.post("/api/auth/login", json={"username": "gustavo", "password": "errada"})
            assert bad.status_code == 401

            # 4. Login válido retorna token de sessão HMAC e seta cookie
            ok = client.post(
                "/api/auth/login",
                json={"username": "gustavo", "password": "minha-senha-forte"},
            )
            assert ok.status_code == 200
            token = ok.json()["token"]
            assert token

            # 5. Com token/cookie, /api/auth/status e /api/finance/summary funcionam
            st2 = client.get("/api/auth/status", headers={"X-Access-Token": token}).json()
            assert st2["authenticated"] is True
            assert (
                client.get("/api/finance/summary", headers={"X-Access-Token": token}).status_code
                == 200
            )
    finally:
        get_settings.cache_clear()
