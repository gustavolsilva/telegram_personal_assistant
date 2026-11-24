"""Roteador central de comandos, mensagens e callbacks entre módulos."""

from __future__ import annotations

from core.module_base import AssistantModule, CommandSpec
from telegram import Update
from telegram.ext import ContextTypes


class ModuleRouter:
    """Gerencia o registro e despacho de intenções para os módulos ativos."""

    def __init__(self) -> None:
        self._modules: list[AssistantModule] = []
        self._command_map: dict[str, AssistantModule] = {}

    def register(self, module: AssistantModule) -> None:
        self._modules.append(module)
        self._modules.sort(key=lambda m: m.priority)
        for spec in module.get_commands():
            self._command_map[spec.command.lstrip("/").lower()] = module

    @property
    def modules(self) -> list[AssistantModule]:
        return list(self._modules)

    def all_commands(self) -> list[CommandSpec]:
        specs: list[CommandSpec] = []
        for mod in self._modules:
            specs.extend(mod.get_commands())
        return specs

    async def dispatch_command(
        self,
        command: str,
        args: list[str],
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> bool:
        mod = self._command_map.get(command.lstrip("/").lower())
        if mod is None:
            return False
        return await mod.handle_command(command.lstrip("/").lower(), args, update, context)

    async def dispatch_text(
        self,
        text: str,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> bool:
        for mod in self._modules:
            if mod.can_handle_text(text):
                handled = await mod.handle_text(text, update, context)
                if handled:
                    return True
        return False

    async def dispatch_callback(
        self,
        data: str,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> bool:
        if ":" not in data:
            return False
        mod_name, _, rest = data.partition(":")
        action, _, payload = rest.partition(":")
        for mod in self._modules:
            if mod.name == mod_name:
                return await mod.handle_callback(action, payload, update, context)
        return False

    async def dispatch_media(
        self,
        media_type: str,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> bool:
        for mod in self._modules:
            handled = await mod.handle_media(media_type, update, context)
            if handled:
                return True
        return False

