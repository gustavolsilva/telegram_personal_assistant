"""Compressão Gzip e criptografia autenticada AES-256-GCM para snapshots."""

from __future__ import annotations

import gzip
import hashlib
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MAGIC_HEADER = b"TPA1"
ASSOCIATED_DATA = b"tpa-snapshot-v1"


def derive_aes_key(secret: str) -> bytes:
    """Deriva chave de 256 bits a partir de STORAGE_ENCRYPTION_KEY usando HKDF-SHA256."""
    cleaned = secret.strip()
    if not cleaned:
        raise ValueError("STORAGE_ENCRYPTION_KEY não configurada.")
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"telegram-personal-assistant-salt",
        info=b"sqlite-snapshot-aes256gcm",
    )
    return hkdf.derive(cleaned.encode("utf-8"))


def sha256_hex(data: bytes) -> str:
    """Retorna o digest SHA-256 em hexadecimal."""
    return hashlib.sha256(data).hexdigest()


def encrypt_snapshot(raw_bytes: bytes, secret: str) -> bytes:
    """Comprime com gzip e criptografa usando AES-256-GCM."""
    key = derive_aes_key(secret)
    compressed = gzip.compress(raw_bytes, compresslevel=6)
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, compressed, ASSOCIATED_DATA)
    return MAGIC_HEADER + nonce + ciphertext


def decrypt_snapshot(encrypted_bytes: bytes, secret: str) -> bytes:
    """Valida cabeçalho, descriptografa AES-256-GCM e descomprime gzip."""
    if len(encrypted_bytes) < len(MAGIC_HEADER) + 12 + 16:
        raise ValueError("Arquivo de snapshot corrompido ou truncado.")
    if not encrypted_bytes.startswith(MAGIC_HEADER):
        raise ValueError("Formato de snapshot inválido (cabeçalho ausente).")

    key = derive_aes_key(secret)
    offset = len(MAGIC_HEADER)
    nonce = encrypted_bytes[offset : offset + 12]
    ciphertext = encrypted_bytes[offset + 12 :]

    compressed = AESGCM(key).decrypt(nonce, ciphertext, ASSOCIATED_DATA)
    return gzip.decompress(compressed)

