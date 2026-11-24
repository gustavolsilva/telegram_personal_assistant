"""Entrypoint unificado: FastAPI (API + PWA) e Worker do Bot do Telegram."""

from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager

from core.auth import is_authorized_telegram_user
from core.config import PROJECT_ROOT, get_settings
from core.database import DatabaseManager
from core.router import ModuleRouter
from core.telegram_storage import TelegramStorageManager
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from modules.finance.api import create_finance_router
from modules.finance.handlers import FinanceModule
from modules.finance.seed import seed_defaults
from modules.finance.service import FinanceService
from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("assistant")


def _build_telegram_app(
    token: str,
    router: ModuleRouter,
) -> Application:
    app = (
        Application.builder()
        .token(token)
        .connect_timeout(15.0)
        .read_timeout(15.0)
        .write_timeout(15.0)
        .build()
    )

    async def on_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if not is_authorized_telegram_user(user.id if user else None):
            return
        if update.effective_message is None or not update.effective_message.text:
            return
        parts = update.effective_message.text.strip().split()
        cmd = parts[0].lstrip("/").split("@")[0].lower()
        args = parts[1:]
        if cmd == "start":
            await router.dispatch_command("ajuda", args, update, context)
            return
        handled = await router.dispatch_command(cmd, args, update, context)
        if not handled:
            await update.effective_message.reply_text(
                "Comando não reconhecido. Envie /ajuda para ver as opções."
            )

    async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if not is_authorized_telegram_user(user.id if user else None):
            return
        if update.effective_message is None or not update.effective_message.text:
            return
        handled = await router.dispatch_text(update.effective_message.text, update, context)
        if not handled:
            await update.effective_message.reply_text(
                "Não identifiquei um valor nessa mensagem. Ex: '45,90 almoço nubank' ou /ajuda."
            )

    async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if not is_authorized_telegram_user(user.id if user else None):
            return
        if update.callback_query and update.callback_query.data:
            await router.dispatch_callback(update.callback_query.data, update, context)

    for spec in router.all_commands():
        app.add_handler(CommandHandler(spec.command, on_command))
    app.add_handler(CommandHandler("start", on_command))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app


def create_app() -> FastAPI:
    settings = get_settings()
    db = DatabaseManager(settings.effective_database_url)
    router = ModuleRouter()
    storage: TelegramStorageManager | None = None
    tg_app: Application | None = None

    if settings.telegram_bot_token:
        tg_app = _build_telegram_app(settings.telegram_bot_token, router)
        if settings.sync_enabled and settings.storage_channel_id and settings.storage_encryption_key:
            storage = TelegramStorageManager(
                bot=tg_app.bot,
                channel_id=settings.storage_channel_id,
                encryption_key=settings.storage_encryption_key,
                sqlite_path=settings.sqlite_path,
                debounce_seconds=settings.sync_debounce_seconds,
            )

    finance_service = FinanceService(db.session_factory, storage=storage)
    if storage is not None:
        async def _on_snap(snap):
            await finance_service.record_sync_state(
                pinned_msg_id=snap.pinned_msg_id,
                file_id=snap.file_id,
                checksum_sha256=snap.checksum_sha256,
                synced_at=snap.synced_at,
            )
        storage.set_snapshot_callback(_on_snap)

    finance_api = create_finance_router(finance_service)
    finance_mod = FinanceModule(
        service=finance_service,
        api_router=finance_api,
        web_dashboard_url=settings.effective_public_url,
    )
    router.register(finance_mod)

    # Registra comandos do módulo no tg_app antes de polling ou webhook
    if tg_app is not None:
        cmd_callback = tg_app.handlers[0][0].callback
        for spec in router.all_commands():
            tg_app.add_handler(CommandHandler(spec.command, cmd_callback))

    db_initialized = False
    tg_initialized = False
    init_lock = asyncio.Lock()

    async def _ensure_initialized() -> None:
        nonlocal db_initialized, tg_initialized
        if db_initialized and (tg_app is None or tg_initialized):
            return
        async with init_lock:
            if not db_initialized:
                await db.create_tables()
                async with db.session_factory() as session:
                    await seed_defaults(session)
                db_initialized = True
            if tg_app is not None and not tg_initialized:
                await tg_app.initialize()
                tg_initialized = True

    @asynccontextmanager
    async def lifespan(_fastapi_app: FastAPI):
        await _ensure_initialized()

        tg_started = False
        tg_task: asyncio.Task[None] | None = None

        async def _start_telegram_with_retry() -> None:
            nonlocal tg_started
            assert tg_app is not None
            delay = 5
            while True:
                try:
                    await _ensure_initialized()
                    await tg_app.bot.set_my_commands(
                        [BotCommand(s.command, s.description) for s in router.all_commands()]
                    )
                    await tg_app.start()
                    if tg_app.updater is not None:
                        await tg_app.updater.start_polling(drop_pending_updates=False)
                    tg_started = True
                    logger.info("Bot do Telegram iniciado em modo Long Polling.")
                    return
                except asyncio.CancelledError:
                    return
                except Exception as exc:
                    logger.warning(
                        "Falha temporária ao conectar Bot do Telegram (%s). Tentando novamente em %ds...",
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 60)

        if tg_app is not None and not settings.is_vercel:
            tg_task = asyncio.create_task(_start_telegram_with_retry())
        elif settings.is_vercel:
            logger.info("Modo Vercel Serverless ativo: Telegram operando via Webhook.")
        else:
            logger.warning("TELEGRAM_BOT_TOKEN não configurado; rodando apenas API Web.")

        try:
            yield
        finally:
            if tg_task is not None and not tg_task.done():
                tg_task.cancel()
            if tg_app is not None and tg_started:
                if tg_app.updater is not None and tg_app.updater.running:
                    await tg_app.updater.stop()
                await tg_app.stop()
                await tg_app.shutdown()
            await db.dispose()

    fastapi_app = FastAPI(
        title="Telegram Personal Assistant",
        version="0.1.0",
        lifespan=lifespan,
    )
    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    fastapi_app.include_router(finance_api)

    @fastapi_app.get("/api/health")
    async def health() -> dict[str, str]:
        await _ensure_initialized()
        return {"status": "ok", "mode": "vercel" if settings.is_vercel else "local"}

    @fastapi_app.post("/api/telegram/webhook")
    async def telegram_webhook(
        request: Request,
        x_telegram_bot_api_secret_token: str | None = Header(default=None),
    ) -> dict[str, bool]:
        if tg_app is None:
            raise HTTPException(status_code=503, detail="TELEGRAM_BOT_TOKEN não configurado.")
        expected_secret = settings.telegram_webhook_secret.strip()
        if expected_secret and (
            not x_telegram_bot_api_secret_token
            or not secrets.compare_digest(x_telegram_bot_api_secret_token, expected_secret)
        ):
            raise HTTPException(status_code=403, detail="Webhook secret inválido.")

        await _ensure_initialized()
        payload = await request.json()
        update = Update.de_json(payload, tg_app.bot)
        if update is not None:
            await tg_app.process_update(update)
        return {"ok": True}

    web_dir = PROJECT_ROOT / "web"
    if web_dir.exists():
        @fastapi_app.get("/")
        async def serve_index() -> FileResponse:
            return FileResponse(web_dir / "index.html")

        fastapi_app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")

    return fastapi_app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    cfg = get_settings()
    uvicorn.run("app:app", host=cfg.web_host, port=cfg.web_port, reload=False)
