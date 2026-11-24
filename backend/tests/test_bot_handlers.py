"""Testes unitários de funcionamento do Bot do Telegram (comandos, texto livre, callbacks e whitelist)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from core.auth import is_authorized_telegram_user
from core.config import Settings
from core.database import DatabaseManager
from core.router import ModuleRouter
from core.telegram_storage import TelegramStorageManager
from modules.finance.handlers import FinanceModule
from modules.finance.seed import seed_defaults
from modules.finance.service import FinanceService


class FakeChannelBot:
    """Simula a Bot API para postagens, edições e backups no Canal Privado."""

    def __init__(self) -> None:
        self.sent_messages: list[dict] = []
        self.edited_messages: list[dict] = []
        self.pinned_id: int | None = None
        self.next_id = 500

    async def send_message(self, chat_id: int, text: str):
        self.next_id += 1
        self.sent_messages.append({"chat_id": chat_id, "message_id": self.next_id, "text": text})
        return SimpleNamespace(message_id=self.next_id, text=text)

    async def edit_message_text(self, chat_id: int, message_id: int, text: str):
        self.edited_messages.append({"chat_id": chat_id, "message_id": message_id, "text": text})
        return SimpleNamespace(message_id=message_id, text=text)

    async def send_document(self, chat_id: int, document, caption: str):
        self.next_id += 1
        data = document.read()
        return SimpleNamespace(
            message_id=self.next_id,
            caption=caption,
            document=SimpleNamespace(file_id=f"doc_{self.next_id}", file_unique_id=f"u_{self.next_id}"),
            _data=data,
        )

    async def pin_chat_message(self, chat_id: int, message_id: int, disable_notification: bool = True):
        self.pinned_id = message_id


def _make_text_update(text: str, user_id: int = 12345, message_id: int = 10) -> SimpleNamespace:
    msg = SimpleNamespace(
        text=text,
        message_id=message_id,
        reply_html=AsyncMock(),
        reply_text=AsyncMock(),
    )
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        effective_message=msg,
        callback_query=None,
    )


def _make_callback_update(data: str, user_id: int = 12345) -> SimpleNamespace:
    query = SimpleNamespace(
        data=data,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
    )
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        effective_message=None,
        callback_query=query,
    )


@pytest.fixture
async def bot_env(tmp_path):
    db_path = tmp_path / "bot_test.db"
    db = DatabaseManager(f"sqlite+aiosqlite:///{db_path}")
    await db.create_tables()
    async with db.session_factory() as session:
        await seed_defaults(session)

    fake_bot = FakeChannelBot()
    storage = TelegramStorageManager(
        bot=fake_bot,  # type: ignore[arg-type]
        channel_id=-100999888,
        encryption_key="chave-unit-test-bot",
        sqlite_path=db_path,
        debounce_seconds=60,
        min_interval_seconds=0.0,
    )
    service = FinanceService(db.session_factory, storage=storage)
    module = FinanceModule(service=service, web_dashboard_url="http://127.0.0.1:8000")
    router = ModuleRouter()
    router.register(module)

    try:
        yield router, service, fake_bot
    finally:
        await db.dispose()


@pytest.mark.asyncio
async def test_bot_text_registration_and_channel_post(bot_env) -> None:
    router, service, fake_bot = bot_env

    # 1. Registrar despesa via texto natural
    upd_exp = _make_text_update("45,90 almoço nubank")
    handled = await router.dispatch_text(upd_exp.effective_message.text, upd_exp, None)  # type: ignore[arg-type]
    assert handled is True

    upd_exp.effective_message.reply_html.assert_awaited_once()
    reply_text = upd_exp.effective_message.reply_html.call_args.args[0]
    reply_markup = upd_exp.effective_message.reply_html.call_args.kwargs["reply_markup"]
    assert "R$ 45,90" in reply_text
    assert "Alimentação" in reply_text
    assert "Cartão de Crédito" in reply_text
    assert len(reply_markup.inline_keyboard) == 2

    # Verificar se foi postado no Canal Privado
    assert len(fake_bot.sent_messages) == 1
    assert "🔴 DESPESA | R$ 45,90" in fake_bot.sent_messages[0]["text"]

    # 2. Registrar receita via texto natural
    upd_inc = _make_text_update("+2500 salário")
    handled_inc = await router.dispatch_text(upd_inc.effective_message.text, upd_inc, None)  # type: ignore[arg-type]
    assert handled_inc is True
    assert len(fake_bot.sent_messages) == 2
    assert "🟢 RECEITA | R$ 2.500,00" in fake_bot.sent_messages[1]["text"]

    # 3. Texto sem valor não deve ser tratado
    upd_none = _make_text_update("olá tudo bem?")
    assert await router.dispatch_text(upd_none.effective_message.text, upd_none, None) is False


@pytest.mark.asyncio
async def test_bot_commands_hoje_mes_dashboard_ajuda_backup(bot_env) -> None:
    router, _service, fake_bot = bot_env

    # Criar um lançamento primeiro
    upd_tx = _make_text_update("100 mercado pix")
    await router.dispatch_text(upd_tx.effective_message.text, upd_tx, None)  # type: ignore[arg-type]

    for cmd in ("hoje", "mes", "dashboard", "ajuda", "backup"):
        upd = _make_text_update(f"/{cmd}")
        ok = await router.dispatch_command(cmd, [], upd, None)  # type: ignore[arg-type]
        assert ok is True
        upd.effective_message.reply_html.assert_awaited_once()

    # /backup deve ter fixado o snapshot no canal
    assert fake_bot.pinned_id is not None

    # /hoje e /mes devem mostrar o valor lançado
    upd_hoje = _make_text_update("/hoje")
    await router.dispatch_command("hoje", [], upd_hoje, None)  # type: ignore[arg-type]
    assert "R$ 100,00" in upd_hoje.effective_message.reply_html.call_args.args[0]


@pytest.mark.asyncio
async def test_bot_inline_callbacks_edit_and_undo(bot_env) -> None:
    router, service, fake_bot = bot_env

    upd_tx = _make_text_update("50 uber")
    await router.dispatch_text(upd_tx.effective_message.text, upd_tx, None)  # type: ignore[arg-type]
    txs = await service.list_transactions()
    assert len(txs) == 1
    tx = txs[0]

    # 1. Abrir menu de categorias
    cb_cats = _make_callback_update(f"finance:cats:{tx.id}")
    assert await router.dispatch_callback(cb_cats.callback_query.data, cb_cats, None) is True  # type: ignore[arg-type]
    cb_cats.callback_query.edit_message_reply_markup.assert_awaited_once()

    # 2. Trocar categoria para Alimentação
    cats = await service.list_categories()
    food_cat = next(c for c in cats if c.name == "Alimentação")
    cb_setcat = _make_callback_update(f"finance:setcat:{tx.id}|{food_cat.id}")
    assert await router.dispatch_callback(cb_setcat.callback_query.data, cb_setcat, None) is True  # type: ignore[arg-type]
    updated = await service.get_transaction(tx.id)
    assert updated is not None and updated.category_id == food_cat.id
    assert len(fake_bot.edited_messages) == 1

    # 3. Inverter tipo (expense -> income)
    cb_flip = _make_callback_update(f"finance:flip:{tx.id}")
    assert await router.dispatch_callback(cb_flip.callback_query.data, cb_flip, None) is True  # type: ignore[arg-type]
    flipped = await service.get_transaction(tx.id)
    assert flipped is not None and flipped.type == "income"

    # 4. Desfazer lançamento (soft delete + marca [EXCLUÍDO] no canal)
    cb_del = _make_callback_update(f"finance:del:{tx.id}")
    assert await router.dispatch_callback(cb_del.callback_query.data, cb_del, None) is True  # type: ignore[arg-type]
    assert await service.get_transaction(tx.id) is None
    assert "[EXCLUÍDO]" in fake_bot.edited_messages[-1]["text"]


def test_bot_whitelist_blocks_strangers() -> None:
    cfg = Settings(telegram_user_id=777000)
    assert is_authorized_telegram_user(777000, cfg) is True
    assert is_authorized_telegram_user(999999, cfg) is False

