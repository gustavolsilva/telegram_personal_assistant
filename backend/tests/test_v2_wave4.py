"""Testes da Onda 4: tags transversais, metas financeiras e patrimônio líquido consolidado."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app import create_app
from core.config import get_settings
from fastapi.testclient import TestClient


def test_v2_wave4_tags_goals_and_net_worth(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'wave4.db'}")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("WEB_ACCESS_TOKEN", "")
    get_settings.cache_clear()
    try:
        app = create_app()
        with TestClient(app) as client:
            # 1. Lançamento via chat com #tags transversais
            chat_res = client.post(
                "/api/finance/chat",
                json={"message": "150 jantar #viagem #reembolso pix"},
            )
            assert chat_res.status_code == 200
            assert chat_res.json()["refresh"] is True

            txs = client.get("/api/finance/transactions").json()
            assert len(txs) == 1
            assert set(txs[0]["tags"]) == {"viagem", "reembolso"}

            tags_sum = client.get("/api/finance/tags").json()
            assert any(t["tag"] == "viagem" and t["expense_cents"] == 15_000 for t in tags_sum)

            # 2. Metas & Aportes
            target_dt = (datetime.now(UTC) + timedelta(days=120)).isoformat()
            g_res = client.post(
                "/api/finance/goals",
                json={
                    "name": "Reserva de Emergência",
                    "target_cents": 1_000_000,
                    "current_cents": 200_000,
                    "target_date": target_dt,
                    "icon": "🛡️",
                },
            )
            assert g_res.status_code == 201
            goal_id = g_res.json()["id"]

            c_res = client.post(
                f"/api/finance/goals/{goal_id}/contribute",
                json={"delta_cents": 100_000},
            )
            assert c_res.status_code == 200
            assert c_res.json()["current_cents"] == 300_000

            goals = client.get("/api/finance/goals").json()
            assert len(goals) == 1
            assert goals[0]["pct"] == 30.0
            assert goals[0]["monthly_needed_cents"] > 0

            # 3. Patrimônio Consolidado (Liquidez + Investimentos - Passivos)
            a_res = client.post(
                "/api/finance/assets",
                json={
                    "institution": "XP",
                    "asset_class": "renda_fixa",
                    "name": "CDB 110%",
                    "balance_cents": 500_000,
                },
            )
            assert a_res.status_code == 201
            asset_id = a_res.json()["id"]

            nw = client.get("/api/finance/net-worth").json()
            assert nw["invested_cents"] == 500_000
            assert nw["cash_cents"] == -15_000
            assert nw["net_worth_cents"] == 485_000

            upd = client.patch(
                f"/api/finance/assets/{asset_id}",
                json={"balance_cents": 600_000},
            )
            assert upd.status_code == 200
            assert client.get("/api/finance/net-worth").json()["invested_cents"] == 600_000
    finally:
        get_settings.cache_clear()
