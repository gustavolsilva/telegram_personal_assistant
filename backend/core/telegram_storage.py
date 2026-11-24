"""Gerenciador de armazenamento híbrido no Canal Privado do Telegram."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import sqlite3
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.crypto import decrypt_snapshot, encrypt_snapshot, sha256_hex
from telegram import Bot
from telegram.error import RetryAfter, TelegramError

logger = logging.getLogger(__name__)


def _slug_tag(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", normalized.lower()).strip("_")
    return cleaned or "geral"


def format_brl_cents(amount_cents: int) -> str:
    reais = amount_cents / 100
    formatted = f"{reais:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def format_transaction_message(
    *,
    tx_id: str,
    tx_type: str,
    amount_cents: int,
    category_name: str,
    account_name: str,
    description: str,
    occurred_at: datetime,
    deleted: bool = False,
) -> str:
    """Formata um lançamento financeiro como mensagem legível e buscável no canal."""
    valor = format_brl_cents(amount_cents)
    if deleted:
        header = f"🗑️ [EXCLUÍDO] {'DESPESA' if tx_type == 'expense' else 'RECEITA' if tx_type == 'income' else 'TRANSFERÊNCIA'} | {valor}"
    elif tx_type == "income":
        header = f"🟢 RECEITA | {valor}"
    elif tx_type == "transfer":
        header = f"🔁 TRANSFERÊNCIA | {valor}"
    else:
        header = f"🔴 DESPESA | {valor}"

    data_str = occurred_at.strftime("%d/%m/%Y %H:%M")
    ym_tag = occurred_at.strftime("%Y_%m")
    tipo_tag = "receita" if tx_type == "income" else "transferencia" if tx_type == "transfer" else "despesa"
    cat_tag = _slug_tag(category_name)
    acc_tag = _slug_tag(account_name)

    return (
        f"{header}\n"
        f"📂 {category_name} · 💳 {account_name}\n"
        f"📝 {description}\n"
        f"📅 {data_str}\n"
        f"#{tipo_tag} #{cat_tag} #{acc_tag} #{ym_tag}\n"
        f"[id:{tx_id}]"
    )


@dataclass(slots=True)
class ChannelPostResult:
    channel_msg_id: int
    file_id: str | None = None
    file_unique_id: str | None = None


@dataclass(slots=True)
class SnapshotResult:
    pinned_msg_id: int
    file_id: str
    checksum_sha256: str
    size_bytes: int
    synced_at: datetime


class TelegramStorageManager:
    """Orquestra envios ao Canal Privado respeitando rate limit (1 msg/s) e snapshots."""

    def __init__(
        self,
        *,
        bot: Bot,
        channel_id: int,
        encryption_key: str,
        sqlite_path: Path | None = None,
        debounce_seconds: int = 60,
        min_interval_seconds: float = 1.05,
    ) -> None:
        self.bot = bot
        self.channel_id = channel_id
        self.encryption_key = encryption_key
        self.sqlite_path = sqlite_path
        self.debounce_seconds = debounce_seconds
        self.min_interval_seconds = min_interval_seconds

        self._lock = asyncio.Lock()
        self._last_op_ts = 0.0
        self._debounce_task: asyncio.Task[None] | None = None
        self._on_snapshot_callback: Any = None

    def set_snapshot_callback(self, callback: Any) -> None:
        self._on_snapshot_callback = callback

    async def _throttle(self) -> None:
        loop = asyncio.get_running_loop()
        now = loop.time()
        elapsed = now - self._last_op_ts
        if elapsed < self.min_interval_seconds:
            await asyncio.sleep(self.min_interval_seconds - elapsed)
        self._last_op_ts = loop.time()

    async def _call_with_retry(self, coro_factory: Any, retries: int = 3) -> Any:
        for attempt in range(retries):
            async with self._lock:
                await self._throttle()
                try:
                    return await coro_factory()
                except RetryAfter as exc:
                    wait_for = float(exc.retry_after) + 0.5
                    logger.warning("Telegram RetryAfter: aguardando %.1fs", wait_for)
                    await asyncio.sleep(wait_for)
                except TelegramError:
                    if attempt == retries - 1:
                        raise
                    await asyncio.sleep(1.5 * (attempt + 1))
        raise RuntimeError("Falha ao executar chamada ao Telegram após tentativas.")

    async def post_transaction(
        self,
        tx_payload: dict[str, Any],
        *,
        photo_bytes: bytes | None = None,
        voice_bytes: bytes | None = None,
    ) -> ChannelPostResult:
        caption = format_transaction_message(**tx_payload)

        if photo_bytes is not None:
            msg = await self._call_with_retry(
                lambda: self.bot.send_photo(
                    chat_id=self.channel_id,
                    photo=io.BytesIO(photo_bytes),
                    caption=caption[:1024],
                )
            )
            photo = msg.photo[-1]
            return ChannelPostResult(
                channel_msg_id=msg.message_id,
                file_id=photo.file_id,
                file_unique_id=photo.file_unique_id,
            )

        if voice_bytes is not None:
            msg = await self._call_with_retry(
                lambda: self.bot.send_voice(
                    chat_id=self.channel_id,
                    voice=io.BytesIO(voice_bytes),
                    caption=caption[:1024],
                )
            )
            return ChannelPostResult(
                channel_msg_id=msg.message_id,
                file_id=msg.voice.file_id,
                file_unique_id=msg.voice.file_unique_id,
            )

        msg = await self._call_with_retry(
            lambda: self.bot.send_message(chat_id=self.channel_id, text=caption)
        )
        return ChannelPostResult(channel_msg_id=msg.message_id)

    async def update_transaction_message(
        self,
        channel_msg_id: int,
        tx_payload: dict[str, Any],
        *,
        has_media: bool = False,
    ) -> None:
        text = format_transaction_message(**tx_payload)
        if has_media:
            await self._call_with_retry(
                lambda: self.bot.edit_message_caption(
                    chat_id=self.channel_id,
                    message_id=channel_msg_id,
                    caption=text[:1024],
                )
            )
        else:
            await self._call_with_retry(
                lambda: self.bot.edit_message_text(
                    chat_id=self.channel_id,
                    message_id=channel_msg_id,
                    text=text,
                )
            )

    def schedule_snapshot(self) -> None:
        """Agenda envio de snapshot com debounce para evitar uploads em rajada."""
        if self.sqlite_path is None:
            return
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
        self._debounce_task = asyncio.create_task(self._debounced_snapshot_runner())

    async def _debounced_snapshot_runner(self) -> None:
        try:
            await asyncio.sleep(self.debounce_seconds)
            result = await self.upload_snapshot_now()
            if self._on_snapshot_callback is not None:
                await self._on_snapshot_callback(result)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Erro ao executar snapshot agendado no canal.")

    @staticmethod
    def _dump_sqlite_consistent(sqlite_path: Path) -> bytes:
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            src = sqlite3.connect(str(sqlite_path))
            dst = sqlite3.connect(tmp.name)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            return Path(tmp.name).read_bytes()

    async def upload_snapshot_now(self, schema_version: int = 1) -> SnapshotResult:
        if self.sqlite_path is None or not self.sqlite_path.exists():
            raise FileNotFoundError("Arquivo SQLite local não encontrado para snapshot.")

        raw_bytes = await asyncio.to_thread(self._dump_sqlite_consistent, self.sqlite_path)
        raw_sha256 = sha256_hex(raw_bytes)
        encrypted = encrypt_snapshot(raw_bytes, self.encryption_key)
        now = datetime.now(UTC)

        metadata = {
            "type": "tpa_snapshot",
            "version": schema_version,
            "sha256": raw_sha256,
            "raw_bytes": len(raw_bytes),
            "enc_bytes": len(encrypted),
            "synced_at": now.isoformat(),
        }
        caption = f"🔐 SNAPSHOT_SQLITE\n{json.dumps(metadata, ensure_ascii=False)}"

        bio = io.BytesIO(encrypted)
        bio.name = f"snapshot_{now.strftime('%Y%m%d_%H%M%S')}.sqlite.gz.enc"

        msg = await self._call_with_retry(
            lambda: self.bot.send_document(
                chat_id=self.channel_id,
                document=bio,
                caption=caption,
            )
        )
        await self._call_with_retry(
            lambda: self.bot.pin_chat_message(
                chat_id=self.channel_id,
                message_id=msg.message_id,
                disable_notification=True,
            )
        )
        return SnapshotResult(
            pinned_msg_id=msg.message_id,
            file_id=msg.document.file_id,
            checksum_sha256=raw_sha256,
            size_bytes=len(encrypted),
            synced_at=now,
        )

    async def restore_from_channel(self, target_sqlite_path: Path) -> dict[str, Any]:
        """Lê a mensagem fixada do canal, baixa o snapshot, valida e restaura o SQLite."""
        chat = await self._call_with_retry(lambda: self.bot.get_chat(chat_id=self.channel_id))
        pinned = chat.pinned_message
        if pinned is None or pinned.document is None:
            raise RuntimeError("Nenhuma mensagem fixada com snapshot encontrada no canal.")

        meta_line = (pinned.caption or "").splitlines()[-1]
        metadata = json.loads(meta_line)
        expected_sha256 = metadata["sha256"]

        tg_file = await self._call_with_retry(
            lambda: self.bot.get_file(file_id=pinned.document.file_id)
        )
        buf = io.BytesIO()
        await tg_file.download_to_memory(out=buf)
        encrypted_bytes = buf.getvalue()

        raw_bytes = decrypt_snapshot(encrypted_bytes, self.encryption_key)
        actual_sha256 = sha256_hex(raw_bytes)
        if actual_sha256 != expected_sha256:
            raise ValueError("Checksum SHA-256 do snapshot restaurado não confere!")

        target_sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_target = target_sqlite_path.with_suffix(".db.restore_tmp")
        tmp_target.write_bytes(raw_bytes)
        tmp_target.replace(target_sqlite_path)

        return {
            "restored_bytes": len(raw_bytes),
            "sha256": actual_sha256,
            "metadata": metadata,
        }

