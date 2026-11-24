"""Entrypoint Serverless da Vercel para FastAPI + Telegram Webhook."""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import app as _fastapi_app  # noqa: E402


async def app(scope, receive, send):  # type: ignore[no-untyped-def]
    """Restaura o path original /api/... quando reescrito via vercel.json."""
    if scope["type"] == "http":
        raw_qs = scope.get("query_string", b"").decode("latin-1")
        params = parse_qsl(raw_qs, keep_blank_values=True)
        restored_path = None
        remaining = []
        for k, v in params:
            if k == "__path" and restored_path is None:
                restored_path = v
            else:
                remaining.append((k, v))
        if restored_path is not None:
            scope = dict(scope)
            scope["path"] = f"/api/{restored_path.lstrip('/')}"
            scope["raw_path"] = scope["path"].encode("latin-1")
            scope["query_string"] = urlencode(remaining).encode("latin-1")
    await _fastapi_app(scope, receive, send)
