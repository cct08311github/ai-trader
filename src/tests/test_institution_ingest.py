"""Tests for institution_ingest.py — targeting 100% coverage."""

import json
import sqlite3
from unittest.mock import patch


# ── _fetch_text ────────────────────────────────────────────────────────────────

def test_fetch_text_success():
    """Lines 31-33: _fetch_text fetches URL and decodes response."""
    from openclaw.institution_ingest import _fetch_text

    import io
    from urllib.error import URLError

    class FakeResp:
        def read(self):
            return b"hello world"
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    with patch("openclaw.institution_ingest.urlopen", return_value=FakeResp()):
        result = _fetch_text("http://example.com")
    assert result == "hello world"


# ── _clean_symbol ──────────────────────────────────────────────────────────────

def test_clean_symbol_strip_suffixes():
    """Line 40: _clean_symbol strips known Taiwan suffixes."""
    from openclaw.institution_ingest import _clean_symbol
    assert _clean_symbol("2330.TW") == "2330"
    assert _clean_symbol("2317.TWO") == "2317"
    assert _clean_symbol("1234.TWSE") == "1234"
    assert _clean_symbol("5678.TPEX") == "5678"
    assert _clean_symbol("ABC") == "ABC"


# ── _to_float ──────────────────────────────────────────────────────────────────

def test_to_float_none_input():
    """Line 47: _to_float returns None for None."""
    from openclaw.institution_ingest import _to_float
    assert _to_float(None) is None


def test_to_float_empty_and_dashes():
    """Line 50: _to_float returns None for empty/N/A strings."""
    from openclaw.institution_ingest import _to_float
    assert _to_float("") is None
    assert _to_float("--") is None
    assert _to_float("---") is None
    assert _to_float("N/A") is None


def test_to_float_plus_sign_and_commas():
    """Lines 51-52: _to_float strips + sign and commas."""
    from openclaw.institution_ingest import _to_float
    assert _to_float("+1,234.5") == 1234.5
    assert _to_float("1,000") == 1000.0


def test_to_float_invalid_string():
    """Lines 55-56: _to_float returns None for unconvertible strings."""
    from openclaw.institution_ingest import _to_float
    assert _to_float("abc") is None
    assert _to_float("1.2.3") is None


# ── _sign ──────────────────────────────────────────────────────────────────────

def test_sign_function():
    """Lines 60-64: _sign returns 1/-1/0."""
    from openclaw.institution_ingest import _sign
    assert _sign(5.0) == 1
    assert _sign(-3.0) == -1
    assert _sign(0.0) == 0


# ── calculate_chip_health_score ─────────────────────────────────────────────────

def test_chip_health_all_positive():
    """Lines 84-112: positive net buys, aligned -> high score."""
    from openclaw.institution_ingest import calculate_chip_health_score
    score = calculate_chip_health_score(500_000, 300_000, 200_000)
    assert 0.0 <= score <= 1.0
    assert score > 0.5


def test_chip_health_all_negative():
    """Lines 84-112: all net sells -> score below 0.5."""
    from openclaw.institution_ingest import calculate_chip_health_score
    score = calculate_chip_health_score(-500_000, -300_000, -200_000)
    assert score < 0.5


def test_chip_health_direction_zero_mixed():
    """Line 110: total=0 with mixed signs -> score=0.5."""
    from openclaw.institution_ingest import calculate_chip_health_score
    # total = 0 and at least 2 non-zero signs -> score=0.5
    score = calculate_chip_health_score(500_000, -500_000, 0)
    assert abs(score - 0.5) < 1e-9


# ── parse_institution_payload ─────────────────────────────────────────────────

def test_parse_non_dict_items_skipped():
    """Line 143: non-dict items are skipped."""
    from openclaw.institution_ingest import parse_institution_payload
    payload = ["not_a_dict", None, 42]
    rows = parse_institution_payload(payload, trade_date="2026-01-01")
    assert rows == []


def test_parse_missing_symbol_skipped():
    """Line 147: rows with empty symbol are skipped."""
    from openclaw.institution_ingest import parse_institution_payload
    payload = [{"Code": "", "ForeignNet": 100, "InvestmentTrustNet": 50, "DealerNet": 20}]
    rows = parse_institution_payload(payload, trade_date="2026-01-01")
    assert rows == []


def test_parse_using_buy_sell_fallback():
    """Lines 158-171: falls back to Buy/Sell fields when Net fields are absent."""
    from openclaw.institution_ingest import parse_institution_payload
    payload = [{
        "Code": "2330",
        "ForeignBuy": "500000",
        "ForeignSell": "200000",
        "InvestmentTrustBuy": "100000",
        "InvestmentTrustSell": "50000",
        "DealerBuy": "80000",
        "DealerSell": "30000",
    }]
    rows = parse_institution_payload(payload, trade_date="2026-01-01")
    assert len(rows) == 1
    assert rows[0].symbol == "2330"
    assert rows[0].foreign_net == 300_000.0
    assert rows[0].investment_trust_net == 50_000.0
    assert rows[0].dealer_net == 50_000.0


def test_parse_chinese_buy_sell_fallback():
    """Lines 158-171: Chinese field name aliases for buy/sell fallback."""
    from openclaw.institution_ingest import parse_institution_payload
    payload = [{
        "證券代號": "0050",
        "外資買進": "200000",
        "外資賣出": "100000",
        "投信買進": "50000",
        "投信賣出": "20000",
        "自營商買進": "30000",
        "自營商賣出": "10000",
    }]
    rows = parse_institution_payload(payload, trade_date="2026-01-01")
    assert len(rows) == 1
    assert rows[0].symbol == "0050"


def test_parse_missing_net_fields_skipped():
    """Lines 173-175: row with all None nets is skipped."""
    from openclaw.institution_ingest import parse_institution_payload
    payload = [{"Code": "1234", "SomeOtherField": "irrelevant"}]
    rows = parse_institution_payload(payload, trade_date="2026-01-01")
    assert rows == []


def test_parse_with_trade_date_extraction():
    """Lines 115-124 (_extract_trade_date): uses embedded date from field."""
    from openclaw.institution_ingest import parse_institution_payload
    payload = [{
        "Code": "2330",
        "trade_date": "2026-03-01",
        "ForeignNet": "100000",
        "InvestmentTrustNet": "50000",
        "DealerNet": "20000",
    }]
    rows = parse_institution_payload(payload, trade_date="2026-01-01")
    assert rows[0].trade_date == "2026-03-01"


# ── fetch_institution_flows ───────────────────────────────────────────────────

def test_fetch_institution_flows_non_list_response():
    """Line 205: non-list JSON response -> return empty list."""
    from openclaw.institution_ingest import fetch_institution_flows

    def fake_fetcher(url, timeout):
        return '{"error": "not a list"}'

    result = fetch_institution_flows("2026-01-01", fetcher=fake_fetcher)
    assert result == []


def test_fetch_institution_flows_success():
    """Lines 203-207: successful fetch and parse."""
    from openclaw.institution_ingest import fetch_institution_flows

    def fake_fetcher(url, timeout):
        return json.dumps([{
            "Code": "2330",
            "ForeignNet": "500000",
            "InvestmentTrustNet": "200000",
            "DealerNet": "100000",
        }])

    rows = fetch_institution_flows("2026-01-01", fetcher=fake_fetcher)
    assert len(rows) == 1
    assert rows[0].symbol == "2330"


# ── ensure_schema + upsert_institution_flows ──────────────────────────────────

def test_upsert_institution_flows():
    """Lines 229-261: upsert creates schema and inserts rows."""
    from openclaw.institution_ingest import (
        upsert_institution_flows, get_institution_flows,
        InstitutionFlowRow, ensure_schema,
    )

    conn = sqlite3.connect(":memory:")
    rows = [
        InstitutionFlowRow(
            trade_date="2026-01-01",
            symbol="2330",
            foreign_net=100_000.0,
            investment_trust_net=50_000.0,
            dealer_net=20_000.0,
            total_net=170_000.0,
            health_score=0.75,
            source_url="http://test",
        )
    ]
    n = upsert_institution_flows(conn, rows)
    assert n == 1

    fetched = get_institution_flows(conn, trade_date="2026-01-01")
    assert len(fetched) == 1
    assert fetched[0].symbol == "2330"


# ── record_ingest_run ──────────────────────────────────────────────────────────

def test_record_ingest_run():
    """Lines 275-298: record_ingest_run creates table and inserts run record."""
    from openclaw.institution_ingest import record_ingest_run

    conn = sqlite3.connect(":memory:")
    run_id = record_ingest_run(
        conn,
        trade_date="2026-01-01",
        status="ok",
        rows=5,
        source_url="http://test",
        error_text="",
    )
    assert run_id
    row = conn.execute("SELECT status, rows FROM institution_ingest_runs WHERE run_id = ?", (run_id,)).fetchone()
    assert row[0] == "ok"
    assert row[1] == 5


# ── get_institution_flows ─────────────────────────────────────────────────────

def test_get_institution_flows_with_symbol_filter():
    """Lines 311-337: get_institution_flows with symbol filter."""
    from openclaw.institution_ingest import (
        upsert_institution_flows, get_institution_flows, InstitutionFlowRow,
    )

    conn = sqlite3.connect(":memory:")
    rows = [
        InstitutionFlowRow("2026-01-01", "2330", 100_000.0, 50_000.0, 20_000.0, 170_000.0, 0.75, "http://t"),
        InstitutionFlowRow("2026-01-01", "0050", -50_000.0, -10_000.0, -5_000.0, -65_000.0, 0.30, "http://t"),
    ]
    upsert_institution_flows(conn, rows)

    fetched = get_institution_flows(conn, symbol="2330")
    assert len(fetched) == 1
    assert fetched[0].symbol == "2330"


def test_get_institution_flows_no_filter():
    """Lines 311-337: get_institution_flows with no filter returns all rows."""
    from openclaw.institution_ingest import (
        upsert_institution_flows, get_institution_flows, InstitutionFlowRow,
    )

    conn = sqlite3.connect(":memory:")
    rows = [
        InstitutionFlowRow("2026-01-01", "2330", 100_000.0, 50_000.0, 20_000.0, 170_000.0, 0.75, "http://t"),
        InstitutionFlowRow("2026-01-01", "0050", -50_000.0, -10_000.0, -5_000.0, -65_000.0, 0.30, "http://t"),
    ]
    upsert_institution_flows(conn, rows)
    fetched = get_institution_flows(conn)
    assert len(fetched) == 2


# ── get_market_summary ─────────────────────────────────────────────────────────

def test_get_market_summary_no_data():
    """Line 351: get_market_summary returns zeros when no data."""
    from openclaw.institution_ingest import get_market_summary, ensure_schema

    conn = sqlite3.connect(":memory:")
    ensure_schema(conn)
    summary = get_market_summary(conn, "2026-01-01")
    assert summary["total_symbols"] == 0


def test_get_market_summary_with_data():
    """Lines 340-365: get_market_summary returns correct aggregation."""
    from openclaw.institution_ingest import (
        upsert_institution_flows, get_market_summary, InstitutionFlowRow,
    )

    conn = sqlite3.connect(":memory:")
    rows = [
        InstitutionFlowRow("2026-01-01", "2330", 100_000.0, 50_000.0, 20_000.0, 170_000.0, 0.75, "http://t"),
        InstitutionFlowRow("2026-01-01", "0050", 80_000.0, 30_000.0, 10_000.0, 120_000.0, 0.70, "http://t"),
    ]
    upsert_institution_flows(conn, rows)
    summary = get_market_summary(conn, "2026-01-01")
    assert summary["total_symbols"] == 2
    assert abs(summary["total_foreign"] - 180_000.0) < 0.01


# ── get_symbol_trend ──────────────────────────────────────────────────────────

def test_get_symbol_trend():
    """Line 368-369: get_symbol_trend delegates to get_institution_flows."""
    from openclaw.institution_ingest import (
        upsert_institution_flows, get_symbol_trend, InstitutionFlowRow,
    )

    conn = sqlite3.connect(":memory:")
    rows = [
        InstitutionFlowRow("2026-01-01", "2330", 100_000.0, 50_000.0, 20_000.0, 170_000.0, 0.75, "http://t"),
    ]
    upsert_institution_flows(conn, rows)
    trend = get_symbol_trend(conn, "2330", days=3)
    assert len(trend) == 1


# ── calculate_alignment_score ─────────────────────────────────────────────────

def test_alignment_score_all_active_same_positive():
    """Line 382: all positive -> score=1.0."""
    from openclaw.institution_ingest import calculate_alignment_score
    assert calculate_alignment_score(100.0, 200.0, 50.0) == 1.0


def test_alignment_score_all_active_same_negative():
    """Line 382: all negative -> score=0.0."""
    from openclaw.institution_ingest import calculate_alignment_score
    assert calculate_alignment_score(-100.0, -200.0, -50.0) == 0.0


def test_alignment_score_all_zero():
    """Line 377: all zero -> score=0.5."""
    from openclaw.institution_ingest import calculate_alignment_score
    assert calculate_alignment_score(0.0, 0.0, 0.0) == 0.5


def test_alignment_score_mixed():
    """Line 384: mixed signs -> score=0.5."""
    from openclaw.institution_ingest import calculate_alignment_score
    assert calculate_alignment_score(100.0, -50.0, 20.0) == 0.5


# ── generate_text_chart ───────────────────────────────────────────────────────

def test_generate_text_chart_empty():
    """Line 389: empty rows -> returns 'No data for chart'."""
    from openclaw.institution_ingest import generate_text_chart
    result = generate_text_chart([])
    assert result == "No data for chart"


def test_generate_text_chart_with_data():
    """Lines 387-400: chart generated for non-empty rows."""
    from openclaw.institution_ingest import generate_text_chart, InstitutionFlowRow

    rows = [
        InstitutionFlowRow("2026-01-01", "2330", 100_000.0, 50_000.0, 20_000.0, 170_000.0, 0.75, "http://t"),
        InstitutionFlowRow("2026-01-01", "0050", -50_000.0, -10_000.0, -5_000.0, -65_000.0, 0.30, "http://t"),
    ]
    chart = generate_text_chart(rows)
    assert "2330" in chart
    assert "0050" in chart
    assert "+" in chart or "-" in chart


# ── get_chip_health_for_decision ──────────────────────────────────────────────

def test_get_chip_health_no_data():
    """Line 406: returns default when no data available."""
    from openclaw.institution_ingest import get_chip_health_for_decision, ensure_schema

    conn = sqlite3.connect(":memory:")
    ensure_schema(conn)
    result = get_chip_health_for_decision(conn, "2330", "2026-01-01")
    assert result["available"] is False
    assert result["health_score"] == 0.5


def test_get_chip_health_with_data():
    """Lines 403-416: returns chip health data when row exists."""
    from openclaw.institution_ingest import (
        upsert_institution_flows, get_chip_health_for_decision, InstitutionFlowRow,
    )

    conn = sqlite3.connect(":memory:")
    rows = [
        InstitutionFlowRow("2026-01-01", "2330", 100_000.0, 50_000.0, 20_000.0, 170_000.0, 0.75, "http://t"),
    ]
    upsert_institution_flows(conn, rows)
    result = get_chip_health_for_decision(conn, "2330", "2026-01-01")
    assert result["available"] is True
    assert result["health_score"] == 0.75


# ── evaluate_chip_health ──────────────────────────────────────────────────────

def test_evaluate_chip_health_no_data():
    """Line 422: CHIP_DATA_UNAVAILABLE -> allowed=True."""
    from openclaw.institution_ingest import evaluate_chip_health, ensure_schema

    conn = sqlite3.connect(":memory:")
    ensure_schema(conn)
    result = evaluate_chip_health(conn, "2330", "2026-01-01")
    assert result["allowed"] is True
    assert result["reason"] == "CHIP_DATA_UNAVAILABLE"


def test_evaluate_chip_health_ok():
    """Lines 419-430: CHIP_HEALTH_OK when score >= threshold."""
    from openclaw.institution_ingest import (
        upsert_institution_flows, evaluate_chip_health, InstitutionFlowRow,
    )

    conn = sqlite3.connect(":memory:")
    rows = [
        InstitutionFlowRow("2026-01-01", "2330", 100_000.0, 50_000.0, 20_000.0, 170_000.0, 0.75, "http://t"),
    ]
    upsert_institution_flows(conn, rows)
    result = evaluate_chip_health(conn, "2330", "2026-01-01", threshold=0.50)
    assert result["allowed"] is True
    assert result["reason"] == "CHIP_HEALTH_OK"


def test_evaluate_chip_health_low():
    """Lines 419-430: CHIP_HEALTH_LOW when score < threshold."""
    from openclaw.institution_ingest import (
        upsert_institution_flows, evaluate_chip_health, InstitutionFlowRow,
    )

    conn = sqlite3.connect(":memory:")
    rows = [
        InstitutionFlowRow("2026-01-01", "0050", -50_000.0, -10_000.0, -5_000.0, -65_000.0, 0.30, "http://t"),
    ]
    upsert_institution_flows(conn, rows)
    result = evaluate_chip_health(conn, "0050", "2026-01-01", threshold=0.45)
    assert result["allowed"] is False
    assert result["reason"] == "CHIP_HEALTH_LOW"
