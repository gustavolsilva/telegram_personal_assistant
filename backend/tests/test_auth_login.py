"""Testes da tela de Login, navegador confiável e 2FA opcional via Telegram."""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, patch

from app import create_app
from core.config import get_settings
from fastapi.testclient import TestClient


def test_login_and_protected_api(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("WEB_ACCESS_USER", "gustavo")
    monkeypatch.setenv("WEB_ACCESS_TOKEN", "minha-senha-forte")
    monkeypatch.setenv("WEB_2FA_ENABLED", "false")

    get_settings.cache_clear()
    try:
        app = create_app()
        with TestClient(app) as client:
            st = client.get("/api/auth/status").json()
            assert st["auth_required"] is True
            assert st["authenticated"] is False
            assert st["username_required"] is True
            assert st["two_fa_enabled"] is False

            assert client.get("/api/finance/summary").status_code == 401

            bad = client.post(
                "/api/auth/login",
                json={"username": "gustavo", "password": "errada", "trust_browser": True},
            )
            assert bad.status_code == 401

            ok = client.post(
                "/api/auth/login",
                json={"username": "gustavo", "password": "minha-senha-forte", "trust_browser": True},
            )
            assert ok.status_code == 200
            token = ok.json()["token"]
            assert token

            st2 = client.get("/api/auth/status", headers={"X-Access-Token": token}).json()
            assert st2["authenticated"] is True
            assert (
                client.get("/api/finance/summary", headers={"X-Access-Token": token}).status_code
                == 200
            )
    finally:
        get_settings.cache_clear()


def test_optional_2fa_telegram_otp_flow(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'auth2fa.db'}")
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST_TOKEN")
    monkeypatch.setenv("TELEGRAM_USER_ID", "999111")
    monkeypatch.setenv("SYNC_ENABLED", "false")
    monkeypatch.setenv("WEB_ACCESS_USER", "gustavo")
    monkeypatch.setenv("WEB_ACCESS_TOKEN", "minha-senha-forte")
    monkeypatch.setenv("WEB_2FA_ENABLED", "true")

    get_settings.cache_clear()
    try:
        app = create_app()
        with (
            patch("telegram.ext.Application.initialize", new=AsyncMock()),
            patch("telegram.Bot.send_message", new=AsyncMock()) as mock_send,
            TestClient(app) as client,
        ):
            res = client.post(
                "/api/auth/login",
                json={"username": "gustavo", "password": "minha-senha-forte", "trust_browser": True},
            )
            assert res.status_code == 200
            data = res.json()
            assert data["requires_2fa"] is True
            assert data["authenticated"] is False
            challenge = data["challenge_token"]

            # Extrai o código de 6 dígitos enviado para o Telegram
            sent_text = mock_send.call_args.kwargs["text"]
            m = re.search(r"<code>(\d{6})</code>", sent_text)
            assert m is not None
            code = m.group(1)

            # Código errado falha
            bad_2fa = client.post(
                "/api/auth/verify-2fa",
                json={"challenge_token": challenge, "code": "000000", "trust_browser": True},
            )
            assert bad_2fa.status_code == 401

            # Código correto libera sessão de navegador confiável
            ok_2fa = client.post(
                "/api/auth/verify-2fa",
                json={"challenge_token": challenge, "code": code, "trust_browser": True},
            )
            assert ok_2fa.status_code == 200
            assert ok_2fa.json()["authenticated"] is True
            assert ok_2fa.json()["token"]
    finally:
        get_settings.cache_clear()
