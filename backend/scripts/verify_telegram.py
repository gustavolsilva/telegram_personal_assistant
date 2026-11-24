"""Script de validação de conectividade com a Bot API e permissões do Canal Privado."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from telegram import Bot
from telegram.error import TelegramError


def _load_dotenv(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


async def verify() -> int:
    root = Path(__file__).resolve().parents[2]
    _load_dotenv(root / ".env")

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    user_id_raw = os.getenv("TELEGRAM_USER_ID", "").strip()
    channel_id_raw = os.getenv("STORAGE_CHANNEL_ID", "").strip()

    missing = [
        name
        for name, val in [
            ("TELEGRAM_BOT_TOKEN", token),
            ("TELEGRAM_USER_ID", user_id_raw),
            ("STORAGE_CHANNEL_ID", channel_id_raw),
        ]
        if not val
    ]
    if missing:
        print(f"[ERRO] Variáveis ausentes no .env: {', '.join(missing)}")
        print("Consulte docs/setup_telegram.md para preencher o .env.")
        return 1

    try:
        user_id = int(user_id_raw)
        channel_id = int(channel_id_raw)
    except ValueError:
        print("[ERRO] TELEGRAM_USER_ID e STORAGE_CHANNEL_ID devem ser números inteiros.")
        return 1

    bot = Bot(token=token)
    try:
        me = await bot.get_me()
        print(f"[OK] Bot autenticado: @{me.username} (id={me.id})")

        chat = await bot.get_chat(chat_id=channel_id)
        print(f"[OK] Canal encontrado: {chat.title!r} (id={chat.id})")

        msg = await bot.send_message(
            chat_id=channel_id,
            text="🔧 Teste de conectividade do Assistente Pessoal (pode ignorar).",
        )
        print(f"[OK] Postagem no canal funcionando (message_id={msg.message_id})")

        await bot.edit_message_text(
            chat_id=channel_id,
            message_id=msg.message_id,
            text="🔧 Teste de edição no canal OK.",
        )
        print("[OK] Edição de mensagem no canal funcionando")

        await bot.pin_chat_message(
            chat_id=channel_id,
            message_id=msg.message_id,
            disable_notification=True,
        )
        print("[OK] Fixação de mensagem (pin) funcionando")

        await bot.unpin_chat_message(chat_id=channel_id, message_id=msg.message_id)
        await bot.delete_message(chat_id=channel_id, message_id=msg.message_id)
        print("[OK] Limpeza da mensagem de teste concluída")

        print(f"[OK] Whitelist configurada para TELEGRAM_USER_ID={user_id}")
        return 0
    except TelegramError as exc:
        print(f"[ERRO Telegram] {exc}")
        return 1
    finally:
        await bot.shutdown()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(verify()))

