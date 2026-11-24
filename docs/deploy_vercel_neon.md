# Deploy Gratuito na Vercel + Neon Postgres + Webhook (Opção 3)

Com esta configuração, **o Bot e o Dashboard PWA rodam 24/7 na nuvem gratuita da Vercel**, sem precisar deixar o notebook ligado.

## 1. Criar o Banco Gratuito no Neon Postgres
1. Acesse [neon.tech](https://neon.tech) (ou adicione o **Neon** direto pelo **Vercel Marketplace -> Storage**).
2. Crie um projeto gratuito (*Free Tier*).
3. Copie a **Connection String** (ex.: `postgresql://usuario:senha@ep-xxx.neon.tech/neondb?sslmode=require`).

## 2. Subir o Projeto na Vercel
1. Faça push do repositório para o **GitHub** (ou instale a CLI da Vercel com `npm i -g vercel`).
2. Na Vercel (**Add New Project**), importe este repositório.
   - O arquivo [vercel.json](../vercel.json) e o entrypoint [api/index.py](../api/index.py) já estão configurados automaticamente.
3. Em **Settings -> Environment Variables**, adicione:
   - `DATABASE_URL` = sua string do Neon (`postgresql://...`)
   - `TELEGRAM_BOT_TOKEN` = token do `@BotFather`
   - `TELEGRAM_USER_ID` = seu ID numérico
   - `TELEGRAM_WEBHOOK_SECRET` = uma senha aleatória (ex.: `secrets.token_urlsafe(24)`)
   - `STORAGE_CHANNEL_ID` = ID do seu Canal Privado (`-100...`)
   - `STORAGE_ENCRYPTION_KEY` = mesma chave do `.env`
   - `WEB_ACCESS_TOKEN` = senha para proteger seu Dashboard público (recomendado!)
   - `PUBLIC_URL` = `https://<seu-projeto>.vercel.app`
4. Faça o **Deploy** (`Production`).

## 3. Registrar o Webhook do Telegram (1 comando)
Depois que a URL `https://<seu-projeto>.vercel.app` estiver no ar, execute no seu terminal local (com o mesmo `TELEGRAM_BOT_TOKEN` e `TELEGRAM_WEBHOOK_SECRET` no `.env`):

```bash
uv run python backend/scripts/setup_webhook.py https://<seu-projeto>.vercel.app
```

Pronto! A partir desse momento:
- Cada mensagem no Telegram dispara instantaneamente `POST /api/telegram/webhook` na Vercel;
- O saldo/extrato fica persistido no **Neon Postgres** + feed legível no **Canal Privado do Telegram**;
- O Dashboard Bento PWA abre em `https://<seu-projeto>.vercel.app` com HTTPS nativo (pronto para instalar na tela inicial do celular!).

