# Operação Contínua, Acesso no Celular e Disaster Recovery

## 1. Rodar em Background no Linux (`systemd --user`)

Crie o arquivo `~/.config/systemd/user/telegram-assistant.service`:

```ini
[Unit]
Description=Telegram Personal Assistant (Bot + PWA)
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/gustavo/Projects/telegram_personal_assistant/backend
ExecStart=/home/gustavo/Projects/telegram_personal_assistant/.venv/bin/python app.py
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

Ative e inicie o serviço:

```bash
systemctl --user daemon-reload
systemctl --user enable --now telegram-assistant
systemctl --user status telegram-assistant
```

Para ver logs em tempo real:

```bash
journalctl --user -u telegram-assistant -f
```

---

## 2. Acessar o Dashboard PWA pelo Celular (Fora de Casa)

### Opção A — Tailscale (Mais simples)
1. Instale o **Tailscale** no computador e no smartphone com a mesma conta.
2. No `.env`, defina `WEB_HOST=0.0.0.0` e preencha `WEB_ACCESS_TOKEN` com uma senha forte.
3. No navegador do celular, acesse `http://<IP-TAILSCALE-DO-PC>:8000`.
4. Toque em **Adicionar à tela inicial** para usar como aplicativo.

### Opção B — Cloudflare Tunnel (HTTPS nativo)
1. Instale `cloudflared` no computador.
2. Execute `cloudflared tunnel --url http://127.0.0.1:8000` (ou configure um túnel nomeado).
3. Acesse a URL `https://...` no celular (o HTTPS habilita instalação PWA completa e Service Worker offline).

---

## 3. Disaster Recovery (Restaurar do Canal Privado)

Se você trocar de computador ou perder o arquivo `data/assistant.db`:
1. Preencha o `.env` com o mesmo `TELEGRAM_BOT_TOKEN`, `STORAGE_CHANNEL_ID` e `STORAGE_ENCRYPTION_KEY`.
2. Execute:

```bash
uv run python -c "
import asyncio
from pathlib import Path
from telegram import Bot
from core.config import get_settings
from core.telegram_storage import TelegramStorageManager

async def main():
    cfg = get_settings()
    bot = Bot(cfg.telegram_bot_token)
    storage = TelegramStorageManager(
        bot=bot,
        channel_id=cfg.storage_channel_id,
        encryption_key=cfg.storage_encryption_key,
    )
    res = await storage.restore_from_channel(Path('data/assistant.db'))
    print('Restaurado:', res)
    await bot.shutdown()

asyncio.run(main())
"
```

