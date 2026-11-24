"""Registra a URL do Webhook do Telegram na Vercel e atualiza a lista de comandos do Bot."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import get_settings
from telegram import Bot, BotCommand


async def main() -> int:
    if len(sys.argv) < 2:
        print("Uso: uv run python backend/scripts/setup_webhook.py https://<seu-projeto>.vercel.app")
        return 1

    base_url = sys.argv[1].rstrip("/")
    webhook_url = f"{base_url}/api/telegram/webhook"
    cfg = get_settings()
    if not cfg.telegram_bot_token:
        print("[ERRO] TELEGRAM_BOT_TOKEN não configurado no .env.")
        return 1

    bot = Bot(token=cfg.telegram_bot_token)
    try:
        secret = cfg.telegram_webhook_secret.strip() or None
        ok = await bot.set_webhook(url=webhook_url, secret_token=secret, drop_pending_updates=False)
        print(f"[{'OK' if ok else 'ERRO'}] Webhook registrado: {webhook_url}")

        await bot.set_my_commands(
            [
                BotCommand("saldo", "Saldo atual das contas e faturas"),
                BotCommand("vencimentos", "Lembretes de cartões e contas fixas vencendo"),
                BotCommand("fixas", "Listar e pagar contas fixas/anuais"),
                BotCommand("nova_fixa", "Cadastrar conta fixa: /nova_fixa Luz 180 15"),
                BotCommand("nova_conta", "Criar conta: /nova_conta Bradesco 1500"),
                BotCommand("novo_cartao", "Criar cartão: /novo_cartao Inter 10"),
                BotCommand("parcelas", "Parcelamentos ativos e futuros no cartão"),
                BotCommand("ajustar_saldo", "Ajustar saldo: /ajustar_saldo pix 1500"),
                BotCommand("hoje", "Resumo financeiro de hoje"),
                BotCommand("mes", "Resumo e comparativo do mês atual"),
                BotCommand("dashboard", "Link do painel web"),
                BotCommand("ajuda", "Como registrar gastos e ganhos"),
            ]
        )
        print("[OK] Comandos do Bot atualizados no Telegram.")
        return 0
    finally:
        await bot.shutdown()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

