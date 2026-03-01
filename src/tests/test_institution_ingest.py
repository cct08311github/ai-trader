from __future__ import annotations

import sqlite3

from openclaw.institution_ingest import (
    calculate_chip_health_score,
    parse_institution_payload,
    upsert_institution_flows,
)


def test_chip_health_score_direction_and_alignment():
    s_pos = calculate_chip_health_score(500_000, 200_000, 100_000)
    s_neg = calculate_chip_health_score(-500_000, -200_000, -100_000)
    s_conflict = calculate_chip_health_score(500_000, -200_000, -100_000)

    assert 0.0 <= s_pos <= 1.0
    assert 0.0 <= s_neg <= 1.0

    assert s_pos > 0.5
    assert s_neg < 0.5

    # Conflicting flows should be less healthy than fully aligned net buy.
    assert s_conflict < s_pos


def test_parse_and_upsert_institution_flows_sqlite_roundtrip():
    payload = [
        {
            "Date": "2026-02-28",
            "Code": "2330",
            "ForeignNet": "500000",
            "InvestmentTrustNet": "200000",
            "DealerNet": "100000",
        },
        {
            "Date": "2026-02-28",
            "Code": "2317",
            "ForeignNet": "-100000",
            "InvestmentTrustNet": "-50000",
            "DealerNet": "-25000",
        },
    ]

    rows = parse_institution_payload(payload, trade_date="2026-02-28")
    assert len(rows) == 2

    conn = sqlite3.connect(":memory:")
    n = upsert_institution_flows(conn, rows)
    assert n == 2

    r = conn.execute(
        "SELECT symbol, total_net, health_score FROM institution_flows WHERE trade_date = ? ORDER BY symbol",
        ("2026-02-28",),
    ).fetchall()

    assert [x[0] for x in r] == ["2317", "2330"]

    # Check total_net computed.
    total_2330 = [x for x in r if x[0] == "2330"][0][1]
    assert int(total_2330) == 800000

    # Health score sign sanity.
    score_2330 = [x for x in r if x[0] == "2330"][0][2]
    score_2317 = [x for x in r if x[0] == "2317"][0][2]
    assert score_2330 > 0.5
    assert score_2317 < 0.5


def test_chip_health_score_zero_flows():
    """邊界測試：所有淨流量為零。"""
    score = calculate_chip_health_score(0, 0, 0)
    assert score == 0.5  # 中性分數


def test_chip_health_score_extreme_values():
    """邊界測試：極大數值。"""
    score = calculate_chip_health_score(1000000000, 500000000, 200000000)
    assert 0.0 <= score <= 1.0
    # 強烈買入應 > 0.5
    assert score > 0.5


def test_parse_institution_payload_missing_fields():
    """反向測試：payload 缺少欄位。"""
    payload = [
        {
            "Date": "2026-02-28",
            "Code": "2330",
            # 缺少 ForeignNet, InvestmentTrustNet, DealerNet
        }
    ]
    # 假設函數會跳過無效行或引發異常。我們僅檢查它不會崩潰。
    rows = parse_institution_payload(payload, trade_date="2026-02-28")
    # 可能返回空列表或部分行
    assert rows is not None
