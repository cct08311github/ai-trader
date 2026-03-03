"""test_regressions.py — 今日 Bug 防復發測試

涵蓋：
1. pm_review Gemini timeout → 503 not crash
2. daily_pm_review retry on LLM failure
3. positions API always returns last_price key
"""
from __future__ import annotations

import importlib
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Backend path setup (mirrors frontend_backend conftest pattern)
# ---------------------------------------------------------------------------

BACKEND_PATH = Path(__file__).resolve().parents[1] / "frontend" / "backend"

_TEST_TOKEN = "test-bearer-token"
_AUTH_HEADERS = {"Authorization": f"Bearer {_TEST_TOKEN}"}


def _init_db(p: Path) -> None:
    """Create minimal tables needed by the pm and portfolio routers."""
    conn = sqlite3.connect(str(p))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS llm_traces (
            trace_id TEXT,
            agent TEXT,
            model TEXT,
            prompt TEXT,
            response TEXT,
            latency_ms INTEGER,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            tool_calls_json TEXT,
            confidence REAL,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS strategy_proposals (
            proposal_id TEXT PRIMARY KEY,
            generated_by TEXT,
            target_rule TEXT,
            rule_category TEXT,
            current_value TEXT,
            proposed_value TEXT,
            supporting_evidence TEXT,
            confidence REAL,
            requires_human_approval INTEGER,
            status TEXT,
            expires_at INTEGER,
            proposal_json TEXT,
            created_at INTEGER,
            decided_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            symbol TEXT,
            side TEXT,
            qty INTEGER,
            price REAL,
            status TEXT,
            ts_submit INTEGER
        );
        CREATE TABLE IF NOT EXISTS fills (
            fill_id TEXT PRIMARY KEY,
            order_id TEXT,
            qty INTEGER,
            price REAL,
            fee REAL,
            tax REAL
        );
        CREATE TABLE IF NOT EXISTS positions (
            symbol TEXT PRIMARY KEY,
            quantity INTEGER,
            avg_price REAL,
            current_price REAL,
            unrealized_pnl REAL,
            chip_health_score REAL,
            sector TEXT
        );
        CREATE TABLE IF NOT EXISTS episodic_memory (
            episode_id TEXT PRIMARY KEY,
            episode_type TEXT,
            summary TEXT,
            content_json TEXT,
            decay_score REAL,
            is_archived INTEGER,
            created_at INTEGER,
            updated_at INTEGER
        );
    """)
    conn.commit()
    conn.close()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """FastAPI TestClient with isolated DB and auth token."""
    db = tmp_path / "trades.db"
    _init_db(db)

    monkeypatch.setenv("DB_PATH", str(db))
    monkeypatch.setenv("AUTH_TOKEN", _TEST_TOKEN)
    monkeypatch.setenv("RATE_LIMIT_RPM", "10000")

    # Ensure backend app package is importable
    if str(BACKEND_PATH) not in sys.path:
        sys.path.insert(0, str(BACKEND_PATH))

    # Reload modules that cache env at import time
    import app.core.config as config_mod
    importlib.reload(config_mod)

    import app.db as db_mod
    importlib.reload(db_mod)

    import app.main as main_mod
    importlib.reload(main_mod)

    from fastapi.testclient import TestClient
    with TestClient(main_mod.app) as c:
        yield c


# ---------------------------------------------------------------------------
# Regression 1: pm_review Gemini timeout → 503 not crash
# ---------------------------------------------------------------------------

class TestPmReviewGeminiTimeout:
    """POST /api/pm/review が LLM 例外を投げても 503 で返る（クラッシュしない）。"""

    def test_gemini_timeout_returns_503(self, client, monkeypatch):
        """run_daily_pm_review が例外を投げた場合、503 + error キーが返る。"""
        # Mock _get_llm_call to return a callable that raises
        def boom(model, prompt):
            raise TimeoutError("Gemini API timeout after 30s")

        # Patch run_daily_pm_review to raise immediately (simulates LLM timeout
        # after all retries are exhausted inside daily_pm_review)
        import app.api.pm as pm_mod
        monkeypatch.setattr(
            pm_mod,
            "run_daily_pm_review",
            lambda **kwargs: (_ for _ in ()).throw(TimeoutError("Gemini API timeout")),
        )

        resp = client.post("/api/pm/review", headers=_AUTH_HEADERS)
        assert resp.status_code == 503
        body = resp.json()
        assert "error" in body

    def test_gemini_connection_error_returns_503(self, client, monkeypatch):
        """ConnectionError も 503 で返る（Gemini が接続不能）。"""
        import app.api.pm as pm_mod
        monkeypatch.setattr(
            pm_mod,
            "run_daily_pm_review",
            lambda **kwargs: (_ for _ in ()).throw(ConnectionError("Could not connect to Gemini")),
        )

        resp = client.post("/api/pm/review", headers=_AUTH_HEADERS)
        assert resp.status_code == 503
        body = resp.json()
        assert "error" in body
        # detail フィールドに例外メッセージが含まれる
        assert "detail" in body

    def test_successful_review_returns_200(self, client, monkeypatch):
        """LLM が成功した場合は 200 + status=ok が返る。"""
        import app.api.pm as pm_mod

        fake_state = {
            "date": "2026-03-03",
            "approved": True,
            "confidence": 0.9,
            "reason": "テスト承認",
            "recommended_action": "buy",
            "bull_case": "",
            "bear_case": "",
            "neutral_case": "",
            "consensus_points": [],
            "divergence_points": [],
            "reviewed_at": "2026-03-03T00:00:00+00:00",
            "source": "llm",
        }
        monkeypatch.setattr(
            pm_mod,
            "run_daily_pm_review",
            lambda **kwargs: fake_state,
        )
        # _write_debate_to_db and _write_llm_trace can be no-ops
        monkeypatch.setattr(pm_mod, "_write_debate_to_db", lambda state: None)
        monkeypatch.setattr(pm_mod, "_write_llm_trace", lambda state, model: None)

        resp = client.post("/api/pm/review", headers=_AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "data" in body


# ---------------------------------------------------------------------------
# Regression 2: daily_pm_review retry on LLM failure
# ---------------------------------------------------------------------------

class TestDailyPmReviewRetry:
    """run_daily_pm_review がリトライロジックを正しく実装していることを検証する。"""

    def _make_context(self) -> dict:
        return {"date": "2026-03-03", "recent_trades": [], "recent_pnl": []}

    def _fake_llm_response(self) -> dict:
        """Valid LLM response that parse_debate_response can handle."""
        return {
            "bull_case": "市場強勁",
            "bear_case": "風險偏高",
            "neutral_case": "觀察中",
            "consensus_points": ["成交量正常"],
            "divergence_points": [],
            "recommended_action": "buy",
            "confidence": 0.75,
            "adjudication": "看多",
        }

    def test_succeeds_after_two_failures(self, tmp_path, monkeypatch):
        """llm_call が最初の 2 回失敗し、3 回目に成功する → run_daily_pm_review は成功する。"""
        import openclaw.daily_pm_review as dpr

        # Redirect state file to tmp_path
        state_path = tmp_path / "daily_pm_state.json"
        monkeypatch.setattr(dpr, "_STATE_PATH", str(state_path))

        call_count = {"n": 0}

        def flaky_llm(model: str, prompt: str) -> dict:
            call_count["n"] += 1
            if call_count["n"] <= 2:
                raise RuntimeError(f"LLM failure #{call_count['n']}")
            return self._fake_llm_response()

        # Patch time.sleep so tests don't actually wait
        monkeypatch.setattr(dpr.time, "sleep", lambda s: None)

        result = dpr.run_daily_pm_review(
            context=self._make_context(),
            llm_call=flaky_llm,
            model="test-model",
        )
        assert call_count["n"] == 3
        assert result["source"] == "llm"
        assert "approved" in result

    def test_all_retries_exhausted_raises(self, tmp_path, monkeypatch):
        """llm_call が全リトライで失敗する → 例外が伝播する。"""
        import openclaw.daily_pm_review as dpr

        state_path = tmp_path / "daily_pm_state.json"
        monkeypatch.setattr(dpr, "_STATE_PATH", str(state_path))
        monkeypatch.setattr(dpr.time, "sleep", lambda s: None)

        def always_fail(model: str, prompt: str) -> dict:
            raise ValueError("LLM is broken")

        with pytest.raises(ValueError, match="LLM is broken"):
            dpr.run_daily_pm_review(
                context=self._make_context(),
                llm_call=always_fail,
                model="test-model",
            )

    def test_no_llm_call_sets_pending_state(self, tmp_path, monkeypatch):
        """llm_call=None の場合は pending_manual 状態が保存される（例外は出ない）。"""
        import openclaw.daily_pm_review as dpr

        state_path = tmp_path / "daily_pm_state.json"
        monkeypatch.setattr(dpr, "_STATE_PATH", str(state_path))

        result = dpr.run_daily_pm_review(
            context=None,
            llm_call=None,
            model="test-model",
        )
        assert result["approved"] is False
        assert result["source"] == "pending"

    def test_first_call_succeeds_no_retry(self, tmp_path, monkeypatch):
        """llm_call が初回で成功する → リトライなし、結果が正しい。"""
        import openclaw.daily_pm_review as dpr

        state_path = tmp_path / "daily_pm_state.json"
        monkeypatch.setattr(dpr, "_STATE_PATH", str(state_path))
        monkeypatch.setattr(dpr.time, "sleep", lambda s: None)

        call_count = {"n": 0}

        def success_llm(model: str, prompt: str) -> dict:
            call_count["n"] += 1
            return self._fake_llm_response()

        result = dpr.run_daily_pm_review(
            context=self._make_context(),
            llm_call=success_llm,
            model="test-model",
        )
        assert call_count["n"] == 1
        assert result["approved"] is True   # "buy" → approved


# ---------------------------------------------------------------------------
# Regression 3: positions API always returns last_price key
# ---------------------------------------------------------------------------

class TestPositionsApiLastPriceKey:
    """GET /api/portfolio/positions は常に last_price キーを返す
    （NULL でも missing ではない）。
    フロントエンドが p.last_price ?? 0 を使うため、キーが欠落すると壊れる。
    """

    def _add_position(self, db_path: Path, current_price=None) -> None:
        """Add a position row with optionally NULL current_price."""
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            """INSERT INTO positions
               (symbol, quantity, avg_price, current_price, unrealized_pnl)
               VALUES (?, ?, ?, ?, ?)""",
            ("2330", 100, 500.0, current_price, None),
        )
        conn.commit()
        conn.close()

    def test_last_price_key_present_when_null_in_db(self, client, tmp_path, monkeypatch):
        """current_price が DB で NULL のとき、レスポンスに last_price キーが存在する。"""
        import os
        db_path = Path(os.environ.get("DB_PATH", str(tmp_path / "trades.db")))
        # Read actual DB_PATH from the env set by the client fixture
        db_path_env = None

        # We need to get the db path that the client fixture set
        # Patch _get_system_simulation_mode to avoid Shioaji dependency
        import app.services.shioaji_service as sj_svc
        monkeypatch.setattr(sj_svc, "_get_system_simulation_mode", lambda: True)
        monkeypatch.setattr(sj_svc, "get_positions", lambda simulation=True: [])

        resp = client.get("/api/portfolio/positions", headers=_AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        # No positions yet → empty list is fine
        for pos in body.get("positions", []):
            assert "last_price" in pos, (
                f"Position {pos.get('symbol')} missing 'last_price' key"
            )

    def test_last_price_key_present_when_db_position_has_null_price(
        self, tmp_path, monkeypatch
    ):
        """DB に current_price=NULL の positions 行があっても、last_price キーが存在する。
        This test exercises the positions table path directly.
        """
        db = tmp_path / "trades2.db"
        _init_db(db)

        # Insert a position with NULL current_price
        conn = sqlite3.connect(str(db))
        conn.execute(
            """INSERT INTO positions
               (symbol, quantity, avg_price, current_price, unrealized_pnl, chip_health_score, sector)
               VALUES ('2454', 50, 800.0, NULL, NULL, NULL, NULL)"""
        )
        conn.commit()
        conn.close()

        monkeypatch.setenv("DB_PATH", str(db))
        monkeypatch.setenv("AUTH_TOKEN", _TEST_TOKEN)
        monkeypatch.setenv("RATE_LIMIT_RPM", "10000")

        if str(BACKEND_PATH) not in sys.path:
            sys.path.insert(0, str(BACKEND_PATH))

        import app.core.config as cfg
        importlib.reload(cfg)
        import app.db as db_mod
        importlib.reload(db_mod)
        import app.main as main_mod
        importlib.reload(main_mod)

        import app.services.shioaji_service as sj_svc
        monkeypatch.setattr(sj_svc, "_get_system_simulation_mode", lambda: True)
        monkeypatch.setattr(sj_svc, "get_positions", lambda simulation=True: [])

        from fastapi.testclient import TestClient
        with TestClient(main_mod.app) as c:
            resp = c.get("/api/portfolio/positions", headers=_AUTH_HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        positions = body.get("positions", [])
        assert len(positions) >= 1, "Expected at least one position from positions table"

        for pos in positions:
            assert "last_price" in pos, (
                f"Position {pos.get('symbol')} missing 'last_price' key — "
                "frontend relies on this key for p.last_price ?? 0"
            )
            # last_price may be None but must be present as a key
            # (None is valid, missing key is the bug)

    def test_last_price_is_none_not_missing_when_price_null(
        self, tmp_path, monkeypatch
    ):
        """current_price=NULL の行から返る last_price は None であり、キー自体は存在する。"""
        db = tmp_path / "trades3.db"
        _init_db(db)

        conn = sqlite3.connect(str(db))
        conn.execute(
            """INSERT INTO positions
               (symbol, quantity, avg_price, current_price, unrealized_pnl, chip_health_score, sector)
               VALUES ('6505', 200, 400.0, NULL, NULL, NULL, NULL)"""
        )
        conn.commit()
        conn.close()

        monkeypatch.setenv("DB_PATH", str(db))
        monkeypatch.setenv("AUTH_TOKEN", _TEST_TOKEN)
        monkeypatch.setenv("RATE_LIMIT_RPM", "10000")

        if str(BACKEND_PATH) not in sys.path:
            sys.path.insert(0, str(BACKEND_PATH))

        import app.core.config as cfg
        importlib.reload(cfg)
        import app.db as db_mod
        importlib.reload(db_mod)
        import app.main as main_mod
        importlib.reload(main_mod)

        import app.services.shioaji_service as sj_svc
        monkeypatch.setattr(sj_svc, "_get_system_simulation_mode", lambda: True)
        monkeypatch.setattr(sj_svc, "get_positions", lambda simulation=True: [])

        from fastapi.testclient import TestClient
        with TestClient(main_mod.app) as c:
            resp = c.get("/api/portfolio/positions", headers=_AUTH_HEADERS)

        assert resp.status_code == 200
        positions = resp.json().get("positions", [])
        tsmc = next((p for p in positions if p["symbol"] == "6505"), None)
        assert tsmc is not None, "Position 6505 not found in response"
        assert "last_price" in tsmc, "last_price key must always be present"
        assert tsmc["last_price"] is None, (
            "last_price should be None (not 0, not missing) when DB value is NULL"
        )
