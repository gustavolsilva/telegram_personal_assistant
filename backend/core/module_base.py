"""Contrato base para módulos plugáveis do Assistente Pessoal."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter
from telegram import Update
from telegram.ext import ContextTypes


@dataclass(slots=True)
class CommandSpec:
    """Definição de um comando do bot registrado por um módulo."""

    command: str
    description: str


class AssistantModule(ABC):
    """Interface padrão que todo módulo (Finanças, Tarefas, Notas...) deve implementar."""

    name: str
    display_name: str
    priority: int = 100  # Menor número = maior prioridade no roteamento de texto livre

    @abstractmethod
    def get_commands(self) -> list[CommandSpec]:
        """Lista de comandos (/comando) expostos pelo módulo."""

    @abstractmethod
    async def handle_command(
        self,
        command: str,
        args: list[str],
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> bool:
        """Processa um /comando. Retorna True se tratado."""

    @abstractmethod
    def can_handle_text(self, text: str) -> bool:
        """Indica se o módulo reconhece e deve processar uma mensagem de texto livre."""

    @abstractmethod
    async def handle_text(
        self,
        text: str,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> bool:
        """Processa texto livre. Retorna True se tratado."""

    async def handle_callback(
        self,
        action: str,
        payload: str,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> bool:
        """Processa callback_query com prefixo '<module_name>:<action>:<payload>'."""
        return False

    async def handle_media(
        self,
        media_type: str,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> bool:
        """Processa áudio/foto/documento quando aplicável."""
        return False

    def get_api_router(self) -> APIRouter | None:
        """Retorna router FastAPI opcional do módulo."""
        return None

    async def on_startup(self, app_state: dict[str, Any]) -> None:
        """Hook executado na inicialização do assistente."""
        return None

