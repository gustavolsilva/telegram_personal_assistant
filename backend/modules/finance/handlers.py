"""Módulo Financeiro: integração com Bot do Telegram, Inline Keyboards e Router."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from core.module_base import AssistantModule, CommandSpec
from core.telegram_storage import format_brl_cents
from fastapi import APIRouter
from modules.finance.parser import (
    _parse_br_number_to_cents,
    parse_finance_question,
    parse_ptbr_transaction,
)
from modules.finance.service import FinanceService, TransactionInput
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes


def _is_public_url(url: str) -> bool:
    lower = url.lower()
    return lower.startswith("https://") or (
        lower.startswith("http://")
        and "127.0.0.1" not in lower
        and "localhost" not in lower
    )


def _tx_keyboard(tx_id: str, dashboard_url: str | None = None) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("📂 Categoria", callback_data=f"finance:cats:{tx_id}"),
            InlineKeyboardButton("💳 Conta", callback_data=f"finance:accs:{tx_id}"),
        ],
        [
            InlineKeyboardButton("🔄 Inverter Tipo", callback_data=f"finance:flip:{tx_id}"),
            InlineKeyboardButton("🗑️ Desfazer", callback_data=f"finance:del:{tx_id}"),
        ],
    ]
    if dashboard_url and _is_public_url(dashboard_url):
        rows.append([InlineKeyboardButton("🌐 Ver no App / Navegador", url=dashboard_url)])
    return InlineKeyboardMarkup(rows)


def _format_tx_reply(
    tx: Any,
    prefix: str = "✅ Cadastrado no Aplicativo com sucesso!",
    dashboard_url: str | None = None,
) -> str:
    footer = (
        f"\n\n📱 <i>Ver no App (celular/navegador):</i> {dashboard_url}"
        if dashboard_url
        else ""
    )
    if tx.type == "transfer":
        dest = tx.transfer_to_account.name if getattr(tx, "transfer_to_account", None) else "Destino"
        return (
            f"🔁 <b>Transferência cadastrada no Aplicativo com sucesso!</b>\n\n"
            f"💸 <b>Valor:</b> {format_brl_cents(tx.amount_cents)}\n"
            f"📤 <b>Origem:</b> {tx.account.name}\n"
            f"📥 <b>Destino:</b> {dest}\n"
            f"📝 <b>Descrição:</b> {tx.description}\n"
            f"📅 <b>Data:</b> {tx.occurred_at.strftime('%d/%m/%Y')}"
            f"{footer}"
        )

    emoji = "🟢" if tx.type == "income" else "🔴"
    tipo = "Receita" if tx.type == "income" else "Despesa"
    valor = format_brl_cents(tx.amount_cents)
    data = tx.occurred_at.strftime("%d/%m/%Y")
    return (
        f"{prefix}\n\n"
        f"{emoji} <b>{tipo}:</b> {valor}\n"
        f"📂 <b>Categoria:</b> {tx.category.icon} {tx.category.name}\n"
        f"💳 <b>Conta:</b> {tx.account.name}\n"
        f"📝 <b>Descrição:</b> {tx.description}\n"
        f"📅 <b>Data:</b> {data}"
        f"{footer}"
    )


class FinanceModule(AssistantModule):
    name = "finance"
    display_name = "Controle Financeiro"
    priority = 10

    def __init__(
        self,
        service: FinanceService,
        api_router: APIRouter | None = None,
        web_dashboard_url: str = "http://127.0.0.1:8000",
    ) -> None:
        self.service = service
        self._api_router = api_router
        self.web_dashboard_url = web_dashboard_url

    def get_commands(self) -> list[CommandSpec]:
        return [
            CommandSpec("saldo", "Saldo atual das contas e faturas"),
            CommandSpec("vencimentos", "Lembretes de cartões e contas fixas vencendo"),
            CommandSpec("fixas", "Listar e pagar contas fixas/anuais"),
            CommandSpec("nova_fixa", "Cadastrar conta fixa: /nova_fixa Luz 180 15"),
            CommandSpec("nova_conta", "Criar conta: /nova_conta Bradesco 1500"),
            CommandSpec("novo_cartao", "Criar cartão: /novo_cartao Inter 10"),
            CommandSpec("parcelas", "Parcelamentos ativos e futuros no cartão"),
            CommandSpec("ajustar_saldo", "Ajustar saldo: /ajustar_saldo pix 1500"),
            CommandSpec("hoje", "Resumo financeiro de hoje"),
            CommandSpec("mes", "Resumo e comparativo do mês atual"),
            CommandSpec("dashboard", "Link do painel web e resumo rápido"),
            CommandSpec("backup", "Forçar backup criptografado no canal"),
            CommandSpec("ajuda", "Como registrar gastos e ganhos"),
        ]

    def get_api_router(self) -> APIRouter | None:
        return self._api_router

    def can_handle_text(self, text: str) -> bool:
        return any(ch.isdigit() for ch in text) or parse_finance_question(text) is not None

    async def handle_command(
        self,
        command: str,
        args: list[str],
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> bool:
        msg = update.effective_message
        if msg is None:
            return False

        now = datetime.now(UTC)
        if command == "saldo":
            await self._reply_balances(update, account_hint=" ".join(args) if args else None)
            return True

        if command == "vencimentos":
            dues = await self.service.get_upcoming_dues(days_ahead=7)
            if not dues:
                await msg.reply_text("✅ Nenhum vencimento pendente nos próximos 7 dias!")
                return True
            lines = ["⏰ <b>Lembretes de Vencimento (7 dias)</b>\n"]
            for d in dues:
                when = (
                    f"ATRASADO ({abs(d['days_until_due'])}d)"
                    if d["days_until_due"] < 0
                    else ("HOJE!" if d["days_until_due"] == 0 else f"em {d['days_until_due']}d (dia {d['due_day']})")
                )
                lines.append(f"• {d['title']}: <b>{format_brl_cents(d['amount_cents'])}</b> — {when}")
            await msg.reply_html("\n".join(lines))
            return True

        if command == "fixas":
            bills = await self.service.list_recurring_bills()
            if not bills:
                await msg.reply_text("📄 Nenhuma conta fixa cadastrada ainda. Cadastre pelo Dashboard!")
                return True
            lines = ["📄 <b>Contas Fixas & Anuais</b>\n"]
            buttons: list[list[InlineKeyboardButton]] = []
            for b in bills:
                badge = "✅ Pago" if b["status"] == "paid" else ("🔴 Atrasada" if b["status"] == "overdue" else "⏳ Pendente")
                lines.append(
                    f"• {b['category_icon']} <b>{b['name']}</b>: {format_brl_cents(b['amount_cents'])} (dia {b['due_day']}) — {badge}"
                )
                if b["status"] != "paid":
                    buttons.append([InlineKeyboardButton(f"✅ Pagar {b['name']}", callback_data=f"finance:paybill:{b['id']}")])
            await msg.reply_html(
                "\n".join(lines),
                reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
            )
            return True

        if command == "novo_cartao":
            if len(args) < 2:
                await msg.reply_html(
                    "Uso: <code>/novo_cartao &lt;nome&gt; &lt;dia_vencimento&gt;</code>\nEx.: <code>/novo_cartao Inter 10</code>"
                )
                return True
            try:
                due_day = int(args[-1])
                if not 1 <= due_day <= 31:
                    raise ValueError
            except ValueError:
                await msg.reply_text("Dia de vencimento inválido (use 1 a 31).")
                return True
            name = " ".join(args[:-1])
            acc = await self.service.create_account(name=name, acc_type="credit", due_day=due_day)
            await msg.reply_html(
                f"💳 Cartão <b>{acc.name}</b> criado com vencimento todo dia <b>{acc.due_day}</b>!"
            )
            return True

        if command == "nova_conta":
            if not args:
                await msg.reply_html(
                    "Uso: <code>/nova_conta &lt;nome&gt; [saldo_inicial]</code>\n"
                    "Ex.: <code>/nova_conta Bradesco 1500</code> ou <code>/nova_conta Poupança poupanca 5000</code>"
                )
                return True
            tokens = list(args)
            initial_cents = 0
            acc_type = "checking"
            try:
                if any(ch.isdigit() for ch in tokens[-1]):
                    initial_cents = _parse_br_number_to_cents(tokens.pop())
            except ValueError:
                pass
            if tokens and tokens[-1].lower() in ("corrente", "checking", "poupanca", "poupança", "savings", "carteira", "wallet"):
                raw_t = tokens.pop().lower()
                acc_type = "savings" if "poup" in raw_t or raw_t == "savings" else ("wallet" if raw_t in ("carteira", "wallet") else "checking")
            name = " ".join(tokens).strip()
            if not name:
                await msg.reply_text("Informe o nome da conta. Ex: /nova_conta Bradesco 1500")
                return True
            acc = await self.service.create_account(
                name=name, acc_type=acc_type, initial_balance_cents=initial_cents
            )
            await msg.reply_html(
                f"🏦 Conta <b>{acc.name}</b> criada com saldo inicial de <b>{format_brl_cents(initial_cents)}</b>!"
            )
            return True

        if command == "nova_fixa":
            if len(args) < 3:
                await msg.reply_html(
                    "Uso: <code>/nova_fixa &lt;nome&gt; &lt;valor&gt; &lt;dia_vencimento&gt; [anual &lt;mes&gt;]</code>\n"
                    "Ex.: <code>/nova_fixa Luz 180,50 15</code>\n"
                    "Ex.: <code>/nova_fixa IPVA 1200 20 anual 1</code>"
                )
                return True
            tokens = list(args)
            recurrence = "monthly"
            due_month: int | None = None
            if len(tokens) >= 5 and tokens[-2].lower() == "anual":
                try:
                    due_month = int(tokens[-1])
                    recurrence = "yearly"
                    tokens = tokens[:-2]
                except ValueError:
                    pass
            try:
                due_day = int(tokens[-1])
                amount_cents = _parse_br_number_to_cents(tokens[-2])
                name = " ".join(tokens[:-2]).strip()
                if not name or not (1 <= due_day <= 31) or amount_cents <= 0:
                    raise ValueError
            except (ValueError, IndexError):
                await msg.reply_text("Formato inválido. Ex: /nova_fixa Luz 180,50 15")
                return True

            cats, accs = await self.service.get_match_targets()
            parsed_hint = parse_ptbr_transaction(f"{amount_cents / 100:.2f} {name}", cats, accs)
            cat_id = parsed_hint.category_id if parsed_hint and parsed_hint.category_id else cats[0].id
            acc_id = parsed_hint.account_id if parsed_hint and parsed_hint.account_id else accs[0].id

            bill = await self.service.create_recurring_bill(
                name=name,
                amount_cents=amount_cents,
                due_day=due_day,
                due_month=due_month,
                recurrence=recurrence,
                category_id=cat_id,
                account_id=acc_id,
            )
            tipo_lbl = f"Anual (mês {due_month})" if recurrence == "yearly" else "Mensal"
            await msg.reply_html(
                f"📄 Conta fixa <b>{bill.name}</b> cadastrada!\n"
                f"💸 Valor: {format_brl_cents(bill.amount_cents)} · Venc. dia {bill.due_day} ({tipo_lbl})"
            )
            return True

        if command == "parcelas":
            await self._reply_installments(update)
            return True

        if command == "ajustar_saldo":
            if len(args) < 2:
                await msg.reply_html(
                    "Uso: <code>/ajustar_saldo &lt;conta&gt; &lt;valor&gt;</code>\nEx.: <code>/ajustar_saldo pix 1500,00</code>"
                )
                return True
            val_str = args[-1]
            acc_query = " ".join(args[:-1]).lower()
            try:
                target_cents = _parse_br_number_to_cents(val_str)
            except ValueError:
                await msg.reply_text("Valor inválido. Ex: /ajustar_saldo pix 1500,00")
                return True
            accs = await self.service.list_accounts()
            matched = next((a for a in accs if acc_query in a.name.lower()), None)
            if matched is None:
                names = ", ".join(a.name for a in accs)
                await msg.reply_text(f"Conta não encontrada. Disponíveis: {names}")
                return True
            await self.service.adjust_account_balance(matched.id, target_cents)
            await msg.reply_html(
                f"✅ Saldo de <b>{matched.name}</b> ajustado para <b>{format_brl_cents(target_cents)}</b>."
            )
            return True

        if command == "hoje":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            summary = await self.service.get_summary(start, now)
            txs = await self.service.list_transactions(start=start, end=now, limit=10)
            lines = [
                "📅 <b>Resumo de Hoje</b>",
                f"🟢 Ganhos: {format_brl_cents(summary['income_cents'])}",
                f"🔴 Gastos: {format_brl_cents(summary['expense_cents'])}",
                f"💰 Saldo: {format_brl_cents(summary['balance_cents'])}",
            ]
            if txs:
                lines.append("\n<b>Lançamentos:</b>")
                for tx in txs:
                    s = "+" if tx.type == "income" else "-"
                    lines.append(
                        f"• {s}{format_brl_cents(tx.amount_cents)} · {tx.category.icon} {tx.description}"
                    )
            await msg.reply_html("\n".join(lines))
            return True

        if command == "mes":
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            summary = await self.service.get_summary(start, now)
            cats = await self.service.get_category_breakdown(start, now, "expense")
            lines = [
                f"📊 <b>Resumo de {now.strftime('%m/%Y')}</b>",
                f"🟢 Ganhos: {format_brl_cents(summary['income_cents'])}",
                f"🔴 Gastos: {format_brl_cents(summary['expense_cents'])}",
                f"💰 Saldo: {format_brl_cents(summary['balance_cents'])} ({summary['savings_rate_pct']}% poupado)",
            ]
            if summary["expense_change_pct"] is not None:
                diff = summary["expense_change_pct"]
                sinal = "+" if diff > 0 else ""
                lines.append(f"📈 Gastos vs período anterior: {sinal}{diff}%")
            if cats:
                lines.append("\n<b>Top Categorias de Gasto:</b>")
                for c in cats[:4]:
                    lines.append(
                        f"• {c['icon']} {c['name']}: {format_brl_cents(c['total_cents'])} ({c['share_pct']}%)"
                    )
            await msg.reply_html("\n".join(lines))
            return True

        if command == "dashboard":
            await msg.reply_html(
                f"🌐 <b>Dashboard Financeiro PWA</b>\n\n"
                f"Acesse pelo computador ou celular:\n{self.web_dashboard_url}"
            )
            return True

        if command == "backup":
            if self.service.storage is None:
                await msg.reply_text(
                    "⚠️ Storage do Canal Privado não está configurado no .env."
                )
                return True
            snap = await self.service.storage.upload_snapshot_now()
            await self.service.record_sync_state(
                pinned_msg_id=snap.pinned_msg_id,
                file_id=snap.file_id,
                checksum_sha256=snap.checksum_sha256,
                synced_at=snap.synced_at,
            )
            await msg.reply_html(
                f"🔐 <b>Backup criptografado concluído!</b>\n"
                f"Tamanho: {snap.size_bytes / 1024:.1f} KB\n"
                f"Mensagem fixada no canal: <code>#{snap.pinned_msg_id}</code>"
            )
            return True

        if command == "ajuda":
            await msg.reply_html(
                "🤖 <b>Como usar o Assistente Financeiro</b>\n\n"
                "Envie mensagens naturais como:\n"
                "• <code>45,90 almoço nubank</code>\n"
                "• <code>600 celular 6x cartão</code> (parcelamento automático)\n"
                "• <code>transferi 300 da conta para pix</code>\n"
                "• <code>+5500 salário</code> ou <code>recebi 400 freela pix</code>\n"
                "• <code>Qual meu saldo?</code> ou <code>Saldo no pix?</code>\n\n"
                "Comandos:\n"
                "/saldo · /vencimentos · /fixas · /nova_conta · /novo_cartao · /nova_fixa · /parcelas · /hoje · /mes"
            )
            return True

        return False

    async def _reply_balances(self, update: Update, account_hint: str | None = None) -> None:
        msg = update.effective_message
        if msg is None:
            return
        data = await self.service.get_account_balances()
        accounts = data["accounts"]
        if account_hint:
            hint_l = account_hint.lower()
            filtered = [a for a in accounts if hint_l in a["name"].lower()]
            if filtered:
                accounts = filtered

        lines = ["🏦 <b>Saldos em Contas</b>"]
        for acc in accounts:
            if acc["type"] == "credit":
                used = max(0, acc["expenses_cents"] - acc["incomes_cents"] - acc["initial_balance_cents"])
                fut = acc["future_installments_cents"]
                lines.append(
                    f"💳 <b>{acc['name']}:</b> Fatura atual {format_brl_cents(used)} | Parcelas futuras {format_brl_cents(fut)}"
                )
            else:
                lines.append(f"• <b>{acc['name']}:</b> {format_brl_cents(acc['balance_cents'])}")

        if not account_hint:
            lines.append(f"\n💰 <b>Total Disponível em Contas:</b> {format_brl_cents(data['total_available_cents'])}")
            if data["credit_used_cents"] > 0 or data["credit_future_installments_cents"] > 0:
                lines.append(
                    f"🧾 <b>Total Comprometido no Cartão:</b> {format_brl_cents(data['credit_used_cents'] + data['credit_future_installments_cents'])}"
                )
        await msg.reply_html("\n".join(lines))

    async def _reply_installments(self, update: Update) -> None:
        msg = update.effective_message
        if msg is None:
            return
        items = await self.service.get_active_installments()
        active = [i for i in items if i["remaining_installments"] > 0 or i["total_installments"] > 1]
        if not active:
            await msg.reply_text("💳 Nenhum parcelamento registrado no momento.")
            return

        total_rem = sum(i["remaining_cents"] for i in active)
        lines = ["💳 <b>Parcelamentos Acumulados</b>\n"]
        for item in active[:12]:
            lines.append(
                f"• {item['category_icon']} <b>{item['description']}</b> ({item['account_name']})\n"
                f"  {item['total_installments']}x de {format_brl_cents(item['installment_amount_cents'])} · "
                f"Restam {item['remaining_installments']} ({format_brl_cents(item['remaining_cents'])})"
            )
        lines.append(f"\n📌 <b>Total futuro acumulado:</b> {format_brl_cents(total_rem)}")
        await msg.reply_html("\n".join(lines))

    async def handle_text(
        self,
        text: str,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> bool:
        msg = update.effective_message
        if msg is None:
            return False

        cats, accs = await self.service.get_match_targets()

        question = parse_finance_question(text, accs)
        if question is not None:
            if question.intent == "balance":
                await self._reply_balances(update, account_hint=question.account_hint)
                return True
            if question.intent == "installments":
                await self._reply_installments(update)
                return True
            if question.intent == "summary_today":
                return await self.handle_command("hoje", [], update, context)
            if question.intent == "summary_month":
                return await self.handle_command("mes", [], update, context)

        parsed = parse_ptbr_transaction(text, cats, accs)
        if parsed is None or parsed.category_id is None or parsed.account_id is None:
            return False

        tx_input = TransactionInput(
            tx_type=parsed.tx_type,
            amount_cents=parsed.amount_cents,
            description=parsed.description,
            category_id=parsed.category_id,
            account_id=parsed.account_id,
            occurred_at=parsed.occurred_at,
            source="telegram_text",
            source_msg_id=msg.message_id,
            installments_total=parsed.installments_total,
            transfer_to_account_id=parsed.transfer_to_account_id,
        )

        if parsed.installments_total > 1:
            created = await self.service.create_installments(tx_input)
            first = created[0]
            per_val = format_brl_cents(first.amount_cents)
            tot_val = format_brl_cents(parsed.amount_cents)
            markup = (
                InlineKeyboardMarkup([[InlineKeyboardButton("🌐 Ver no App / Navegador", url=self.web_dashboard_url)]])
                if _is_public_url(self.web_dashboard_url)
                else None
            )
            await msg.reply_html(
                f"💳 <b>Compra parcelada cadastrada no Aplicativo com sucesso!</b>\n\n"
                f"📝 <b>Descrição:</b> {parsed.description}\n"
                f"🔢 <b>Parcelas:</b> {parsed.installments_total}x de {per_val} (Total: {tot_val})\n"
                f"📂 <b>Categoria:</b> {first.category.icon} {first.category.name}\n"
                f"💳 <b>Conta:</b> {first.account.name}\n\n"
                f"📱 <i>Ver no App (celular/navegador):</i> {self.web_dashboard_url}",
                reply_markup=markup,
            )
            return True

        tx = await self.service.create_transaction(tx_input)
        await msg.reply_html(
            _format_tx_reply(tx, dashboard_url=self.web_dashboard_url),
            reply_markup=_tx_keyboard(tx.id, self.web_dashboard_url),
        )
        return True

    async def handle_callback(
        self,
        action: str,
        payload: str,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> bool:
        query = update.callback_query
        if query is None:
            return False
        await query.answer()

        if action == "del":
            ok = await self.service.soft_delete_transaction(payload)
            if ok:
                await query.edit_message_text("🗑️ Lançamento desfeito e atualizado no canal.")
            else:
                await query.edit_message_text("⚠️ Lançamento não encontrado ou já excluído.")
            return True

        if action == "flip":
            tx = await self.service.get_transaction(payload)
            if tx is None:
                return True
            new_type = "income" if tx.type == "expense" else "expense"
            cats = [c for c in await self.service.list_categories() if c.type == new_type]
            new_cat_id = cats[0].id if cats else tx.category_id
            updated = await self.service.update_transaction(
                payload, tx_type=new_type, category_id=new_cat_id
            )
            if updated:
                await query.edit_message_text(
                    _format_tx_reply(updated, "🔄 Tipo atualizado!"),
                    parse_mode="HTML",
                    reply_markup=_tx_keyboard(updated.id),
                )
            return True

        if action == "cats":
            tx = await self.service.get_transaction(payload)
            if tx is None:
                return True
            cats = [c for c in await self.service.list_categories() if c.type == tx.type]
            buttons = [
                [
                    InlineKeyboardButton(
                        f"{c.icon} {c.name}",
                        callback_data=f"finance:setcat:{tx.id}|{c.id}",
                    )
                ]
                for c in cats
            ]
            buttons.append([InlineKeyboardButton("⬅️ Voltar", callback_data=f"finance:back:{tx.id}")])
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))
            return True

        if action == "setcat" and "|" in payload:
            tx_id, _, cat_id = payload.partition("|")
            updated = await self.service.update_transaction(tx_id, category_id=cat_id)
            if updated:
                await query.edit_message_text(
                    _format_tx_reply(updated, "📂 Categoria atualizada!"),
                    parse_mode="HTML",
                    reply_markup=_tx_keyboard(updated.id),
                )
            return True

        if action == "accs":
            tx = await self.service.get_transaction(payload)
            if tx is None:
                return True
            accs = await self.service.list_accounts()
            buttons = [
                [
                    InlineKeyboardButton(
                        f"💳 {a.name}",
                        callback_data=f"finance:setacc:{tx.id}|{a.id}",
                    )
                ]
                for a in accs
            ]
            buttons.append([InlineKeyboardButton("⬅️ Voltar", callback_data=f"finance:back:{tx.id}")])
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))
            return True

        if action == "setacc" and "|" in payload:
            tx_id, _, acc_id = payload.partition("|")
            updated = await self.service.update_transaction(tx_id, account_id=acc_id)
            if updated:
                await query.edit_message_text(
                    _format_tx_reply(updated, "💳 Conta atualizada!"),
                    parse_mode="HTML",
                    reply_markup=_tx_keyboard(updated.id),
                )
            return True

        if action == "back":
            await query.edit_message_reply_markup(reply_markup=_tx_keyboard(payload))
            return True

        if action == "paybill":
            tx = await self.service.pay_recurring_bill(payload)
            if tx:
                await query.edit_message_text(
                    f"✅ Conta fixa paga e registrada: <b>{tx.description}</b> ({format_brl_cents(tx.amount_cents)})",
                    parse_mode="HTML",
                )
            else:
                await query.edit_message_text("⚠️ Conta fixa não encontrada.")
            return True

        return False

