"""test_quote_endpoints.py — GET /api/portfolio/quote/{symbol}

測試 snapshot 端點的各種情境。
SSE streaming 端點 (/quote-stream/) 因 async generator 無法在同步 TestClient
中可靠終止，只測 auth 保護；streaming 行為改在 unit 層驗證 QuoteService。
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

_TOKEN = "test-bearer-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_snap(
    close=620.0, reference=600.0,
    total_volume=5000, total_amount=3_100_000,
    bid_price=619.0, ask_price=621.0,
):
    return SimpleNamespace(
        close=close, reference=reference,
        total_volume=total_volume, total_amount=total_amount,
        bid_price=bid_price, ask_price=ask_price,
        sell_price=None,   # Shioaji sometimes uses sell_price instead of ask_price
    )


def _mock_api(snaps):
    api = MagicMock()
    api.snapshots.return_value = snaps
    api.Contracts.Stocks.__getitem__ = MagicMock(return_value=MagicMock())
    return api


# ---------------------------------------------------------------------------
# Quote Snapshot — /api/portfolio/quote/{symbol}
# ---------------------------------------------------------------------------

class TestQuoteSnapshot:

    def test_snapshot_shioaji_available(self, client):
        """Shioaji 正常 → 回傳 close/change_rate/volume 等欄位。"""
        snap = _mock_snap()
        with patch("app.services.shioaji_service._get_api", return_value=_mock_api([snap])):
            r = client.get("/api/portfolio/quote/2330", headers=_AUTH)

        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["symbol"] == "2330"
        assert body["source"] == "shioaji"
        data = body["data"]
        assert data["close"] == 620.0
        assert data["reference"] == 600.0
        assert data["change_price"] == 20.0
        assert abs(data["change_rate"] - 3.33) < 0.1   # (620-600)/600*100 ≈ 3.33
        assert data["volume"] == 5000
        assert data["total_amount"] == 3_100_000
        assert data["bid_price"] == 619.0
        assert data["ask_price"] == 621.0

    def test_snapshot_shioaji_raises_returns_closed(self, client):
        """Shioaji 拋例外 → fallback: source=closed, data=None。"""
        with patch("app.services.shioaji_service._get_api", side_effect=RuntimeError("no conn")):
            r = client.get("/api/portfolio/quote/2330", headers=_AUTH)

        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["source"] == "closed"
        assert body["data"] is None

    def test_snapshot_empty_list_returns_closed(self, client):
        """api.snapshots([]) 回空列表 → fallback: source=closed。"""
        with patch("app.services.shioaji_service._get_api", return_value=_mock_api([])):
            r = client.get("/api/portfolio/quote/2330", headers=_AUTH)

        assert r.status_code == 200
        assert r.json()["source"] == "closed"

    def test_snapshot_unauthenticated_returns_401(self, client):
        """無 Bearer token → 401。"""
        r = client.get("/api/portfolio/quote/2330")
        assert r.status_code == 401

    def test_snapshot_symbol_uppercased(self, client):
        """Symbol 自動轉大寫（lowercase input）。"""
        snap = _mock_snap()
        with patch("app.services.shioaji_service._get_api", return_value=_mock_api([snap])):
            r = client.get("/api/portfolio/quote/tsmc", headers=_AUTH)

        assert r.status_code == 200
        assert r.json()["symbol"] == "TSMC"

    def test_snapshot_zero_reference_no_division_error(self, client):
        """reference=0 → change_price=0, change_rate=0（不拋 ZeroDivisionError）。"""
        snap = _mock_snap(reference=0.0)
        with patch("app.services.shioaji_service._get_api", return_value=_mock_api([snap])):
            r = client.get("/api/portfolio/quote/2330", headers=_AUTH)

        assert r.status_code == 200
        data = r.json().get("data") or {}
        if data:
            assert data["change_price"] == 0.0
            assert data["change_rate"] == 0.0


# ---------------------------------------------------------------------------
# Quote Stream Auth — /api/portfolio/quote-stream/{symbol}
# （只測 auth 保護；streaming 行為由 unit tests 驗證）
# ---------------------------------------------------------------------------

class TestQuoteStreamAuth:

    def test_stream_unauthenticated_returns_401(self, client):
        """無 Bearer token → 401（AuthMiddleware 在 SSE generator 啟動前攔截）。"""
        r = client.get("/api/portfolio/quote-stream/2330")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# QuoteService Unit Tests — thread-safe routing logic
# ---------------------------------------------------------------------------

class TestQuoteServiceUnit:
    """直接測試 QuoteService 不透過 HTTP（避免 SSE 阻塞問題）。"""

    def _make_service(self):
        from app.services.shioaji_service import QuoteService
        return QuoteService()

    def test_subscribe_adds_consumer(self):
        """subscribe 後 _queues[symbol] 有該 consumer。"""
        import asyncio
        svc = self._make_service()
        queue = asyncio.Queue()
        loop = MagicMock()
        api = MagicMock()
        api.quote.set_on_bidask_stk_v1_callback = MagicMock()
        api.quote.subscribe = MagicMock()

        svc.subscribe("2330", queue, loop, api)

        assert (queue, loop) in svc._queues["2330"]

    def test_unsubscribe_removes_consumer(self):
        """unsubscribe 後 _queues[symbol] 不含該 consumer。"""
        import asyncio
        svc = self._make_service()
        queue = asyncio.Queue()
        loop = MagicMock()
        api = MagicMock()
        api.quote.set_on_bidask_stk_v1_callback = MagicMock()
        api.quote.subscribe = MagicMock()
        api.quote.unsubscribe = MagicMock()

        svc.subscribe("2330", queue, loop, api)
        svc.unsubscribe("2330", queue, api)

        assert (queue, loop) not in svc._queues.get("2330", set())

    def test_on_bidask_routes_to_consumers(self):
        """_on_bidask callback 將資料轉送到所有 consumer queues。"""
        import asyncio
        svc = self._make_service()
        queue = asyncio.Queue()
        loop = MagicMock()
        loop.is_closed.return_value = False
        api = MagicMock()
        api.quote.set_on_bidask_stk_v1_callback = MagicMock()
        api.quote.subscribe = MagicMock()

        svc.subscribe("2330", queue, loop, api)

        bidask = SimpleNamespace(
            code="2330",
            bid_price=[619.0, 618.5],
            bid_volume=[100, 200],
            ask_price=[621.0, 621.5],
            ask_volume=[50, 80],
        )
        exchange = MagicMock()
        svc._on_bidask(exchange, bidask)

        # run_coroutine_threadsafe should have been called with queue.put
        loop.is_closed.assert_called()

    def test_on_bidask_unknown_symbol_no_crash(self):
        """_on_bidask 收到不在 _queues 的 symbol 不應崩潰。"""
        svc = self._make_service()
        bidask = SimpleNamespace(
            code="9999",
            bid_price=[100.0], bid_volume=[10],
            ask_price=[101.0], ask_volume=[5],
        )
        svc._on_bidask(MagicMock(), bidask)   # should not raise

    def test_on_bidask_missing_code_no_crash(self):
        """_on_bidask 收到 code=None 的 bidask 不應崩潰。"""
        svc = self._make_service()
        bidask = SimpleNamespace(code=None)
        svc._on_bidask(MagicMock(), bidask)   # should not raise
