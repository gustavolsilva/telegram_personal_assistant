"""Controle de acesso (Whitelist do Telegram e autenticação Login/Senha da API Web)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from core.config import Settings, get_settings
from fastapi import Cookie, Header, HTTPException, status

SESSION_TTL_SECONDS = 8 * 3600
TRUSTED_SESSION_TTL_SECONDS = 30 * 24 * 3600
TWO_FA_TTL_SECONDS = 300


def is_authorized_telegram_user(user_id: int | None, settings: Settings | None = None) -> bool:
    """Retorna True apenas se o user_id corresponder ao proprietário configurado."""
    if user_id is None:
        return False
    cfg = settings or get_settings()
    if cfg.telegram_user_id is None:
        return False
    return user_id == cfg.telegram_user_id


def create_session_token(secret: str, ttl_seconds: int = SESSION_TTL_SECONDS) -> str:
    """Gera token de sessão assinado com HMAC-SHA256 (sem expor a senha no localStorage)."""
    exp = int(time.time()) + ttl_seconds
    payload = f"tpa:{exp}"
    sig = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def verify_session_or_access_token(provided: str | None, expected_secret: str) -> bool:
    """Aceita tanto o WEB_ACCESS_TOKEN direto quanto um session token HMAC válido."""
    if not expected_secret:
        return True
    if not provided:
        return False
    if secrets.compare_digest(provided, expected_secret):
        return True
    if "." in provided:
        exp_str, _, sig = provided.partition(".")
        try:
            exp = int(exp_str)
        except ValueError:
            return False
        if exp < int(time.time()):
            return False
        payload = f"tpa:{exp}"
        expected_sig = hmac.new(
            expected_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(sig, expected_sig)
    return False


def create_2fa_challenge(secret: str, code: str, ttl_seconds: int = TWO_FA_TTL_SECONDS) -> str:
    """Gera desafio 2FA stateless (compatível com Vercel Serverless) assinado com HMAC-SHA256."""
    exp = int(time.time()) + ttl_seconds
    code_hash = hashlib.sha256(code.strip().encode("utf-8")).hexdigest()
    payload = f"2fa:{exp}:{code_hash}"
    sig = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{exp}.{code_hash}.{sig}"


def verify_2fa_challenge(secret: str, challenge_token: str, code: str) -> bool:
    """Valida desafio 2FA stateless e o código aleatório de 6 dígitos."""
    parts = challenge_token.split(".")
    if len(parts) != 3:
        return False
    exp_str, expected_code_hash, sig = parts
    try:
        exp = int(exp_str)
    except ValueError:
        return False
    if exp < int(time.time()):
        return False
    payload = f"2fa:{exp}:{expected_code_hash}"
    expected_sig = hmac.new(
        secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return False
    provided_hash = hashlib.sha256(code.strip().encode("utf-8")).hexdigest()
    return hmac.compare_digest(provided_hash, expected_code_hash)


def extract_provided_token(
    x_access_token: str | None = None,
    authorization: str | None = None,
    tpa_session: str | None = None,
) -> str | None:
    if x_access_token:
        return x_access_token.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    if tpa_session:
        return tpa_session.strip()
    return None


def verify_web_access_token(
    x_access_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    tpa_session: str | None = Cookie(default=None),
) -> None:
    """Valida token/sessão caso WEB_ACCESS_TOKEN esteja definido."""
    cfg = get_settings()
    expected = cfg.web_access_token.strip()
    if not expected:
        return

    provided = extract_provided_token(x_access_token, authorization, tpa_session)
    if not verify_session_or_access_token(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessão expirada ou senha inválida.",
        )
