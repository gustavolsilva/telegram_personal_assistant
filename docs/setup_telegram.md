# Guia de Provisionamento do Telegram (Fase 0)

Este guia mostra como configurar seu Bot e o Canal Privado de armazenamento em ~3 minutos.

## 1. Criar o Bot no `@BotFather`
1. Abra o Telegram e procure por **@BotFather** (verificado).
2. Envie `/newbot`.
3. Escolha um nome de exibição (ex.: `Meu Assistente Financeiro`).
4. Escolha um `@username` terminado em `bot` (ex.: `gustavo_financas_bot`).
5. Copie o **HTTP API Token** gerado e cole em `TELEGRAM_BOT_TOKEN` no arquivo `.env`.

## 2. Descobrir seu `TELEGRAM_USER_ID`
1. Procure por **@userinfobot** (ou `@raw_data_bot`) no Telegram e envie `/start`.
2. Copie o número de `Id` (ex.: `123456789`) e cole em `TELEGRAM_USER_ID` no `.env`.
   - Apenas esse ID terá permissão para interagir com o seu bot.

## 3. Criar o Canal Privado de Armazenamento
1. No Telegram, crie um **Novo Canal** (`New Channel`).
2. Dê um nome (ex.: `Cofre Financeiro Assistente`) e marque como **Privado** (*Private Channel*).
3. Abra as configurações do canal -> **Administradores** -> **Adicionar Administrador**.
4. Busque o `@username` do seu bot e conceda as permissões:
   - **Postar mensagens** (*Post Messages*)
   - **Editar mensagens** (*Edit Messages*)
   - **Apagar mensagens** (*Delete Messages*)
   - **Fixar mensagens** (*Pin Messages*)
5. Para descobrir o `STORAGE_CHANNEL_ID`:
   - Envie uma mensagem qualquer no canal (ex.: `teste`), encaminhe essa mensagem para o **@userinfobot** (ou **@JsonDumpBot**) e copie o `Forward from chat id` (começa com `-100`, ex.: `-1001234567890`).
   - Cole esse valor em `STORAGE_CHANNEL_ID` no `.env`.

## 4. Gerar a Chave de Criptografia Local
No terminal, dentro da pasta do projeto, execute:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Cole o resultado em `STORAGE_ENCRYPTION_KEY` no `.env` (e guarde uma cópia em seu gerenciador de senhas).

## 5. Validar Conectividade
Depois de preencher o `.env` (copiando de `.env.example`), execute:

```bash
uv run python backend/scripts/verify_telegram.py
```

O script vai testar o token, enviar uma mensagem de teste no canal, fixar, editar e apagar automaticamente, confirmando que todas as permissões estão funcionando.

