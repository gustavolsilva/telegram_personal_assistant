"""Testes da Fase 2: Criptografia, formatação de feed e restore de snapshot."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from core.crypto import decrypt_snapshot, encrypt_snapshot
from core.telegram_storage import (
    TelegramStorageManager,
    format_transaction_message,
)


def test_encrypt_decrypt_roundtrip() -> None:
    secret = "minha-chave-super-secreta-123"
    payload = b"SQLite format 3\x00" + b"dados-financeiros-" * 200
    encrypted = encrypt_snapshot(payload, secret)
    assert encrypted != payload
    assert len(encrypted) < len(payload)  # gzip comprimiu bem

    decrypted = decrypt_snapshot(encrypted, secret)
    assert decrypted == payload

    with pytest.raises(Exception):
        decrypt_snapshot(encrypted, "chave-errada")


def test_format_transaction_message() -> None:
    msg = format_transaction_message(
        tx_id="019abc",
        tx_type="expense",
        amount_cents=4590,
        category_name="Alimentação",
        account_name="Cartão de Crédito",
        description="Almoço executivo",
        occurred_at=datetime(2026, 11, 23, 12, 30, tzinfo=UTC),
    )
    assert "🔴 DESPESA | R$ 45,90" in msg
    assert "#despesa #alimentacao #cartao_de_credito #2026_11" in msg
    assert "[id:019abc]" in msg


class FakeTelegramFile:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def download_to_memory(self, out) -> None:
        out.write(self._data)


class FakeBot:
    def __init__(self) -> None:
        self.messages: dict[int, SimpleNamespace] = {}
        self.pinned_id: int | None = None
        self.next_id = 100

    async def send_message(self, chat_id: int, text: str):
        self.next_id += 1
        msg = SimpleNamespace(message_id=self.next_id, text=text, caption=None, document=None)
        self.messages[msg.message_id] = msg
        return msg

    async def send_document(self, chat_id: int, document, caption: str):
        self.next_id += 1
        data = document.read()
        doc = SimpleNamespace(file_id=f"file_{self.next_id}", file_unique_id=f"uniq_{self.next_id}")
        msg = SimpleNamespace(
            message_id=self.next_id,
            text=None,
            caption=caption,
            document=doc,
            _raw_doc=data,
        )
        self.messages[msg.message_id] = msg
        return msg

    async def pin_chat_message(self, chat_id: int, message_id: int, disable_notification: bool = True):
        self.pinned_id = message_id

    async def get_chat(self, chat_id: int):
        pinned = self.messages.get(self.pinned_id) if self.pinned_id else None
        return SimpleNamespace(id=chat_id, pinned_message=pinned)

    async def get_file(self, file_id: str):
        for msg in self.messages.values():
            if msg.document and msg.document.file_id == file_id:
                return FakeTelegramFile(msg._raw_doc)
        raise FileNotFoundError(file_id)


@pytest.mark.asyncio
async def test_snapshot_backup_and_disaster_recovery(tmp_path) -> None:
    db_path = tmp_path / "assistant.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO items (name) VALUES ('Almoço 45,90')")
    conn.commit()
    conn.close()

    fake_bot = FakeBot()
    storage = TelegramStorageManager(
        bot=fake_bot,  # type: ignore[arg-type]
        channel_id=-100123456,
        encryption_key="chave-teste-fase2",
        sqlite_path=db_path,
        min_interval_seconds=0.0,
    )

    snap = await storage.upload_snapshot_now(schema_version=1)
    assert snap.pinned_msg_id == fake_bot.pinned_id
    assert len(snap.checksum_sha256) == 64

    # Simula perda total do banco local e restaura do canal
    restored_path = tmp_path / "restored" / "assistant.db"
    report = await storage.restore_from_channel(restored_path)
    assert report["sha256"] == snap.checksum_sha256

    r_conn = sqlite3.connect(str(restored_path))
    rows = r_conn.execute("SELECT name FROM items").fetchall()
    r_conn.close()
    assert rows == [("Almoço 45,90",)]
