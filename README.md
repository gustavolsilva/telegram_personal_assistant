# Assistente Pessoal no Telegram (Módulo Financeiro)

Assistente pessoal modular **local-first** integrado ao Telegram, com processamento no computador local, armazenamento híbrido em **Canal Privado do Telegram** (feed legível com `#tags` + snapshot SQLite criptografado com AES-256-GCM) e **Dashboard Web Bento (PWA)** em React + Tailwind CSS + Apache ECharts.

## Funcionalidades Principais

- **Lançamentos por Texto Natural no Bot ou no Dashboard:**
  - Despesas e Receitas: `"45,90 almoço nubank"`, `"+5500 salário"`, `"recebi 400 freela pix"`
  - Parcelamento no Cartão: `"600 celular 6x cartão"` ou `"tênis 3x de 100"` (acumula parcelas nos meses futuros)
  - Transferências entre Contas: `"transferi 500 da conta principal para pix"` ou `"paguei fatura 800"`
- **Consultas Inteligentes:**
  - Pergunte naturalmente `"Qual meu saldo?"`, `"Quanto tenho no pix?"`, `"Parcelas do cartão"` ou `"Quanto gastei hoje?"`.
- **Múltiplos Cartões, Contas Fixas & Despesas de Veículo:**
  - Cadastro tanto pelo **Bot** quanto pelo **Dashboard** (`💳 Fixas & Cartões`).
  - Lembretes de vencimento para faturas de cartões, contas mensais (**Água, Luz, Internet Fixa/Móvel, Aluguel, Financiamento**) e anuais (**IPVA, Licenciamento, Multas**).
- **Dashboard Bento (PWA):**
  - Hero Wallet com saldo disponível, Cartão de Crédito virtual, Fluxo Diário, Custos por Categoria, Comparativo Mensal, Mês Atual vs Anterior, Dia da Semana, Benchmark 3 meses, Exportação CSV e Widget de Chat integrado.

## Comandos do Bot

| Comando | O que faz |
| :--- | :--- |
| `/saldo` | Mostra saldo de todas as contas, fatura atual e parcelas futuras |
| `/vencimentos` | Lista faturas de cartões e contas fixas vencendo nos próximos 7 dias |
| `/fixas` | Lista contas fixas/anuais com botão **✅ Pagar** |
| `/parcelas` | Lista parcelamentos ativos acumulados no cartão |
| `/nova_conta <nome> [saldo]` | Cria conta bancária/poupança/carteira |
| `/novo_cartao <nome> <dia>` | Cria cartão de crédito com dia de vencimento |
| `/nova_fixa <nome> <valor> <dia> [anual <mes>]` | Cadastra conta fixa mensal ou anual (ex.: IPVA) |
| `/ajustar_saldo <conta> <valor>` | Ajusta saldo real de uma conta |
| `/hoje` · `/mes` | Resumo financeiro de hoje e do mês atual |
| `/backup` | Força envio do snapshot criptografado para o Canal Privado |

## Início Rápido

1. Siga [docs/setup_telegram.md](docs/setup_telegram.md) para criar seu Bot no `@BotFather` e o Canal Privado.
2. Copie [`.env.example`](.env.example) para `.env` e preencha suas credenciais.
3. Valide a conexão com o Telegram:
   ```bash
   uv run python backend/scripts/verify_telegram.py
   ```
4. Inicie o Assistente (Bot + API + Dashboard PWA):
   ```bash
   uv run python backend/app.py
   ```
5. Acesse `http://127.0.0.1:8000` no navegador.

## Qualidade & Testes

```bash
uv run ruff check backend
uv run pytest -v
```

Para rodar em background no Linux (`systemd --user`) e acessar pelo celular fora de casa, consulte [docs/operacao_systemd_tailscale.md](docs/operacao_systemd_tailscale.md). Para expandir o assistente com novos módulos, veja [docs/como_criar_modulo.md](docs/como_criar_modulo.md).
