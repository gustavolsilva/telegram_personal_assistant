"""Transcrição de áudio/voz para lançamentos financeiros em PT-BR."""

from __future__ import annotations

import base64
import re

import httpx

GROQ_TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GEMINI_GENERATE_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
)


class VoiceTranscriptionError(RuntimeError):
    """Erro ao transcrever mensagem de voz."""


def normalize_spoken_ptbr(text: str) -> str:
    """Normaliza expressões faladas de valores em reais para o parser PT-BR."""
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return ""

    # "45 reais e 90 centavos" / "45 reais e 90" -> "45,90"
    cleaned = re.sub(
        r"\b(\d+)\s+reais?\s+e\s+(\d{1,2})(?:\s+centavos?)?\b",
        lambda m: f"{m.group(1)},{int(m.group(2)):02d}",
        cleaned,
        flags=re.IGNORECASE,
    )
    # "45 reais" / "1 real" -> "45" / "1"
    cleaned = re.sub(
        r"\b(\d+)\s+reais?\b|\b1\s+real\b",
        lambda m: m.group(1) if m.group(1) else "1",
        cleaned,
        flags=re.IGNORECASE,
    )
    # "45 e 90" (sem 'reais') -> "45,90"
    cleaned = re.sub(
        r"\b(\d+)\s+e\s+(\d{2})\b",
        lambda m: f"{m.group(1)},{m.group(2)}",
        cleaned,
    )
    return cleaned


async def transcribe_audio(
    audio_bytes: bytes,
    *,
    filename: str = "voice.ogg",
    mime_type: str = "audio/ogg",
    groq_api_key: str = "",
    gemini_api_key: str = "",
    timeout_seconds: float = 25.0,
) -> str:
    """Transcreve áudio usando Groq Whisper ou Gemini Flash (gratuitos no tier free)."""
    groq_key = groq_api_key.strip()
    gemini_key = gemini_api_key.strip()

    if groq_key:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            resp = await client.post(
                GROQ_TRANSCRIPTION_URL,
                headers={"Authorization": f"Bearer {groq_key}"},
                files={"file": (filename, audio_bytes, mime_type)},
                data={
                    "model": "whisper-large-v3-turbo",
                    "language": "pt",
                    "response_format": "json",
                    "prompt": (
                        "Transcreva fielmente em português do Brasil para lançamento financeiro, "
                        "usando dígitos para valores (ex: 45,90 almoço nubank)."
                    ),
                },
            )
        if resp.status_code >= 400:
            raise VoiceTranscriptionError(f"Groq HTTP {resp.status_code}: {resp.text[:200]}")
        text = str(resp.json().get("text", "")).strip()
        return normalize_spoken_ptbr(text)

    if gemini_key:
        b64_audio = base64.b64encode(audio_bytes).decode("ascii")
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": (
                                "Transcreva fielmente este áudio em português do Brasil para "
                                "lançamento financeiro, usando dígitos para valores "
                                "(ex: 45,90 almoço nubank). Retorne apenas a frase transcrita, "
                                "sem aspas nem explicações."
                            )
                        },
                        {"inlineData": {"mimeType": mime_type, "data": b64_audio}},
                    ]
                }
            ]
        }
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            resp = await client.post(
                f"{GEMINI_GENERATE_URL}?key={gemini_key}",
                json=payload,
            )
        if resp.status_code >= 400:
            raise VoiceTranscriptionError(f"Gemini HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        candidates = data.get("candidates") or []
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        text = "".join(str(p.get("text", "")) for p in parts).strip()
        return normalize_spoken_ptbr(text)

    raise VoiceTranscriptionError(
        "Transcrição de voz no Telegram requer GROQ_API_KEY ou GEMINI_API_KEY configurada."
    )


async def extract_receipt_command(
    image_bytes: bytes,
    *,
    mime_type: str = "image/jpeg",
    gemini_api_key: str = "",
    timeout_seconds: float = 25.0,
) -> str:
    """Extrai valor, descrição e meio de pagamento de foto de cupom/comprovante Pix via Gemini."""
    gemini_key = gemini_api_key.strip()
    if not gemini_key:
        raise VoiceTranscriptionError(
            "Leitura de foto/comprovante requer GEMINI_API_KEY configurada."
        )

    b64_img = base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": (
                            "Analise esta imagem de cupom fiscal, nota ou comprovante Pix/cartão "
                            "e converta em UMA única linha de lançamento financeiro em português do Brasil, "
                            "no formato: '<valor com vírgula> <descrição curta do estabelecimento/item> <pix|cartão|conta>' "
                            "(se for transferência recebida, comece com '+' antes do valor; se houver parcelamento, inclua ex: '3x'). "
                            "Exemplo: '45,90 padaria pix'. Retorne APENAS essa linha, sem aspas nem explicações."
                        )
                    },
                    {"inlineData": {"mimeType": mime_type, "data": b64_img}},
                ]
            }
        ]
    }
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        resp = await client.post(
            f"{GEMINI_GENERATE_URL}?key={gemini_key}",
            json=payload,
        )
    if resp.status_code >= 400:
        raise VoiceTranscriptionError(f"Gemini Vision HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    candidates = data.get("candidates") or []
    parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
    text = "".join(str(p.get("text", "")) for p in parts).strip()
    return normalize_spoken_ptbr(text)
