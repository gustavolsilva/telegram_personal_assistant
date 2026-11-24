"""Contratos opcionais para IA 100% local (Ollama, Whisper, OCR)."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    @abstractmethod
    async def extract_transaction_json(self, text: str, categories: list[str]) -> dict[str, Any] | None:
        """Extrai estrutura financeira a partir de texto livre ambíguo."""


class OllamaProvider(LLMProvider):
    """Adapter leve via HTTP para Ollama rodando localmente (sem dependências extras)."""

    def __init__(self, base_url: str = "http://127.0.0.1:11434", model: str = "llama3.2") -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def extract_transaction_json(self, text: str, categories: list[str]) -> dict[str, Any] | None:
        prompt = (
            "Extraia em JSON estrito com chaves: type ('expense' ou 'income'), "
            "amount_brl (numero), description (texto curto), category (uma de: "
            f"{', '.join(categories)}). Texto: {text!r}"
        )
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "format": "json",
                        "stream": False,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                res.raise_for_status()
                content = res.json()["message"]["content"]
                return json.loads(content)
        except Exception as exc:
            logger.warning("Ollama indisponível ou falhou no fallback: %s", exc)
            return None

