"""Controle de acesso (Whitelist do Telegram e proteção opcional da API Web)."""

from __future__ import annotations

import secrets

from core.config import Settings, get_settings
from fastapi import Header, HTTPException, status


def is_authorized_telegram_user(user_id: int | None, settings: Settings | None = None) -> bool:
    """Retorna True apenas se o user_id corresponder ao proprietário configurado."""
    if user_id is None:
        return False
    cfg = settings or get_settings()
    if cfg.telegram_user_id is None:
        return False
    return user_id == cfg.telegram_user_id


def verify_web_access_token(
    x_access_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    """Valida token de acesso caso WEB_ACCESS_TOKEN esteja definido no .env."""
    cfg = get_settings()
    expected = cfg.web_access_token.strip()
    if not expected:
        return

    provided = x_access_token
    if not provided and authorization and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()

    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de acesso inválido ou ausente.",
        )

