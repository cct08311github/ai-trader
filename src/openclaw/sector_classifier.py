"""sector_classifier.py — TWSE 產業分類 + 法人資金流向聚合。

功能：
1. 從 TWSE OpenAPI 抓取股票產業分類，建立 symbol-to-sector mapping
2. 硬編碼子產業對應（半導體/電子零組件/金融）
3. 每日聚合 eod_prices 計算產業市值/成交量/漲跌
4. 跨 DB merge：從 trades.db 讀取法人流向，在 Python 層合併，寫入 research.db
5. 主要進入點：run_sector_classifier()
"""
from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 子產業硬編碼對照表（symbol list）
# ---------------------------------------------------------------------------

_SUB_SECTOR_MAP: Dict[str, Dict[str, List[str]]] = {
    "半導體": {
        "IC設計": [
            "2454", "3711", "6770", "3034", "2388", "3231", "6415", "4927",
            "3443", "3086", "6469", "4919", "3533", "6191", "5274",
        ],
        "晶圓代工": ["2330", "2303", "5347", "3036"],
        "封測": ["2325", "2449", "6274", "8150", "2408", "3711"],
        "記憶體": ["3474", "2408", "4919"],
    },
    "電子零組件": {
        "被動元件": ["2327", "2351", "6239", "2308", "2334"],
        "PCB": ["2382", "6269", "3037", "4966", "8046", "3189", "6271"],
        "連接器": ["2492", "3264", "6803", "3005"],
    },
    "金融保險": {
        "金控": ["2882", "2881", "2886", "2884", "2891", "2885", "2887", "2892", "2883", "2888"],
        "銀行": ["2880", "5876", "2889"],
        "保險": ["2823", "2833"],
        "證券": ["2券", "6015", "6016", "2867", "6238"],
    },
}

# 正規化：sector_name → sub_sector，用 symbol 查
_SYMBOL_TO_SUB: Dict[str, str] = {}
for _sector, _subs in _SUB_SECTOR_MAP.items():
    for _sub_name, _symbols in _subs.items():
        for _sym in _symbols:
            _SYMBOL_TO_SUB[_sym] = _sub_name


# ---------------------------------------------------------------------------
# TWSE OpenAPI 抓取
# ---------------------------------------------------------------------------

TWSE_LISTED_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TWSE_COMPANY_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"

_REQUEST_TIMEOUT = 30
_HEADERS = {"Accept": "application/json"}


def _fetch_twse_company_list() -> List[Dict]:
    """抓取 TWSE 上市公司基本資料，包含產業代碼與名稱。

    API: https://openapi.twse.com.tw/v1/opendata/t187ap03_L
    欄位: 公司代號, 公司簡稱, 產業別, ...
    """
    try:
        resp = requests.get(TWSE_COMPANY_URL, headers=_HEADERS, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and data:
            return data
        log.warning("[sector_classifier] TWSE company list returned unexpected format")
        return []
    except requests.RequestException as e:
        log.error("[sector_classifier] Failed to fetch TWSE company list: %s", e)
        return []


def build_sector_mapping(companies: List[Dict]) -> List[Dict]:
    """將 TWSE 公司清單轉換為 sector_mapping 格式。

    Returns list of dicts: symbol, sector_code, sector_name, sub_sector, updated_at
    """
    now_ts = int(time.time())
    rows = []
    for item in companies:
        # TWSE API 欄位可能因版本略異，嘗試常見欄位名
        symbol = (
            item.get("公司代號") or item.get("Code") or item.get("SecuritiesCompanyCode", "")
        ).strip()
        sector_name = (
            item.get("產業別") or item.get("Industry") or item.get("IndustryCode", "")
        ).strip()

        if not symbol or not sector_name:
            continue

        # 產業代碼：取前 4 碼或 sector_name hash，這裡直接用產業別文字當 code
        sector_code = sector_name.replace(" ", "_")[:20]
        sub_sector = _SYMBOL_TO_SUB.get(symbol)

        rows.append({
            "symbol": symbol,
            "sector_code": sector_code,
            "sector_name": sector_name,
            "sub_sector": sub_sector,
            "updated_at": now_ts,
        })
    return rows


def store_sector_mapping(conn: sqlite3.Connection, rows: List[Dict]) -> int:
    """UPSERT sector_mapping；回傳寫入筆數。"""
    if not rows:
        return 0
    sql = """
        INSERT INTO sector_mapping (symbol, sector_code, sector_name, sub_sector, updated_at)
        VALUES (:symbol, :sector_code, :sector_name, :sub_sector, :updated_at)
        ON CONFLICT(symbol) DO UPDATE SET
            sector_code = excluded.sector_code,
            sector_name = excluded.sector_name,
            sub_sector  = excluded.sub_sector,
            updated_at  = excluded.updated_at
    """
    cur = conn.executemany(sql, rows)
    conn.commit()
    return cur.rowcount


# ---------------------------------------------------------------------------
# 讀取 trades.db 資料（跨 DB — 在 Python 層合併）
# ---------------------------------------------------------------------------

def _get_latest_trade_date(trades_conn: sqlite3.Connection) -> Optional[str]:
    row = trades_conn.execute("SELECT MAX(trade_date) AS d FROM eod_prices").fetchone()
    return row[0] if row and row[0] else None


def _load_eod_prices_by_sector(
    trades_conn: sqlite3.Connection,
    sector_map: Dict[str, Tuple[str, str]],
    trade_date: str,
) -> Dict[str, Dict]:
    """從 eod_prices 讀取當日資料，按產業聚合。

    sector_map: symbol -> (sector_code, sector_name)
    回傳: sector_code -> {turnover, market_cap, stock_count, price_changes}
    """
    result: Dict[str, Dict] = {}

    try:
        rows = trades_conn.execute(
            """
            SELECT symbol, close, open, volume, market_cap, change_pct
            FROM eod_prices
            WHERE trade_date = ?
            """,
            (trade_date,),
        ).fetchall()
    except Exception as e:
        log.warning("[sector_classifier] eod_prices query failed: %s", e)
        return result

    for row in rows:
        symbol = row[0] if not hasattr(row, "keys") else row["symbol"]
        close = row[1] if not hasattr(row, "keys") else row["close"]
        volume = row[3] if not hasattr(row, "keys") else row["volume"]
        market_cap = row[4] if not hasattr(row, "keys") else row["market_cap"]
        change_pct = row[5] if not hasattr(row, "keys") else row["change_pct"]

        if symbol not in sector_map:
            continue

        sector_code, sector_name = sector_map[symbol]

        if sector_code not in result:
            result[sector_code] = {
                "sector_code": sector_code,
                "sector_name": sector_name,
                "turnover": 0.0,
                "market_cap": 0.0,
                "stock_count": 0,
                "weighted_change_sum": 0.0,
                "weight_sum": 0.0,
            }

        bucket = result[sector_code]
        bucket["stock_count"] += 1
        turnover_val = float(close or 0) * float(volume or 0)
        bucket["turnover"] += turnover_val
        if market_cap:
            bucket["market_cap"] += float(market_cap)
        # 市值加權漲跌幅
        weight = float(market_cap or 0) if market_cap else 1.0
        bucket["weighted_change_sum"] += float(change_pct or 0) * weight
        bucket["weight_sum"] += weight

    # 計算加權漲跌幅
    for code in result:
        b = result[code]
        if b["weight_sum"] > 0:
            b["change_pct"] = round(b["weighted_change_sum"] / b["weight_sum"], 4)
        else:
            b["change_pct"] = 0.0

    return result


def _load_institution_flows_by_sector(
    trades_conn: sqlite3.Connection,
    sector_map: Dict[str, Tuple[str, str]],
    trade_date: str,
) -> Dict[str, Dict]:
    """從 eod_institution_flows 讀取當日三大法人，按產業聚合。

    回傳: sector_code -> {fund_flow_foreign, fund_flow_trust, fund_flow_net}
    """
    result: Dict[str, Dict] = {}

    try:
        rows = trades_conn.execute(
            """
            SELECT symbol, foreign_net, trust_net
            FROM eod_institution_flows
            WHERE trade_date = ?
            """,
            (trade_date,),
        ).fetchall()
    except Exception as e:
        log.warning("[sector_classifier] eod_institution_flows query failed: %s", e)
        return result

    for row in rows:
        symbol = row[0] if not hasattr(row, "keys") else row["symbol"]
        foreign_net = row[1] if not hasattr(row, "keys") else row["foreign_net"]
        trust_net = row[2] if not hasattr(row, "keys") else row["trust_net"]

        if symbol not in sector_map:
            continue

        sector_code, _ = sector_map[symbol]

        if sector_code not in result:
            result[sector_code] = {"fund_flow_foreign": 0.0, "fund_flow_trust": 0.0}

        result[sector_code]["fund_flow_foreign"] += float(foreign_net or 0)
        result[sector_code]["fund_flow_trust"] += float(trust_net or 0)

    for code in result:
        b = result[code]
        b["fund_flow_net"] = b["fund_flow_foreign"] + b["fund_flow_trust"]

    return result


def _has_todays_institution_flow(trades_conn: sqlite3.Connection, trade_date: str) -> bool:
    """確認 eod_institution_flows 已有今日資料（freshness check）。"""
    try:
        row = trades_conn.execute(
            "SELECT COUNT(*) FROM eod_institution_flows WHERE trade_date = ?",
            (trade_date,),
        ).fetchone()
        cnt = row[0] if row else 0
        return cnt > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 主聚合流程
# ---------------------------------------------------------------------------

def compute_sector_data(
    trades_conn: sqlite3.Connection,
    research_conn: sqlite3.Connection,
    trade_date: Optional[str] = None,
) -> int:
    """聚合當日產業數據，寫入 research.db sector_data。

    Cross-DB merge pattern：
    - trades.db: eod_prices, eod_institution_flows
    - research.db: sector_mapping → sector_data
    所有跨 DB join 在 Python dict 層完成，不使用 ATTACH。

    回傳：寫入筆數。
    """
    # 1. 決定 trade_date
    if trade_date is None:
        trade_date = _get_latest_trade_date(trades_conn)
    if not trade_date:
        log.warning("[sector_classifier] No trade_date available in eod_prices")
        return 0

    # 2. 讀取 sector_mapping
    mapping_rows = research_conn.execute(
        "SELECT symbol, sector_code, sector_name FROM sector_mapping"
    ).fetchall()
    if not mapping_rows:
        log.warning("[sector_classifier] sector_mapping is empty — run fetch first")
        return 0

    sector_map: Dict[str, Tuple[str, str]] = {
        row[0]: (row[1], row[2]) for row in mapping_rows
    }

    # 3. 聚合 eod_prices
    price_data = _load_eod_prices_by_sector(trades_conn, sector_map, trade_date)

    # 4. 聚合法人流向
    flow_data = _load_institution_flows_by_sector(trades_conn, sector_map, trade_date)

    # 5. 合併
    now_ts = int(time.time())
    sector_names: Dict[str, str] = {row[1]: row[2] for row in mapping_rows}

    # 聯集所有出現的 sector_code
    all_codes = set(price_data.keys()) | set(flow_data.keys())

    records = []
    for code in all_codes:
        p = price_data.get(code, {})
        f = flow_data.get(code, {})
        sname = p.get("sector_name") or sector_names.get(code, code)

        records.append({
            "trade_date": trade_date,
            "sector_code": code,
            "sector_name": sname,
            "market_cap": p.get("market_cap"),
            "turnover": p.get("turnover"),
            "change_pct": p.get("change_pct"),
            "fund_flow_net": f.get("fund_flow_net"),
            "fund_flow_foreign": f.get("fund_flow_foreign"),
            "fund_flow_trust": f.get("fund_flow_trust"),
            "pe_ratio": None,  # 暫不聚合 PE，後續擴充
            "stock_count": p.get("stock_count", 0),
            "source": "twse",
            "created_at": now_ts,
        })

    if not records:
        log.warning("[sector_classifier] No sector records to write for %s", trade_date)
        return 0

    sql = """
        INSERT INTO sector_data (
            trade_date, sector_code, sector_name,
            market_cap, turnover, change_pct,
            fund_flow_net, fund_flow_foreign, fund_flow_trust,
            pe_ratio, stock_count, source, created_at
        ) VALUES (
            :trade_date, :sector_code, :sector_name,
            :market_cap, :turnover, :change_pct,
            :fund_flow_net, :fund_flow_foreign, :fund_flow_trust,
            :pe_ratio, :stock_count, :source, :created_at
        )
        ON CONFLICT(trade_date, sector_code) DO UPDATE SET
            sector_name        = excluded.sector_name,
            market_cap         = excluded.market_cap,
            turnover           = excluded.turnover,
            change_pct         = excluded.change_pct,
            fund_flow_net      = excluded.fund_flow_net,
            fund_flow_foreign  = excluded.fund_flow_foreign,
            fund_flow_trust    = excluded.fund_flow_trust,
            pe_ratio           = excluded.pe_ratio,
            stock_count        = excluded.stock_count,
            created_at         = excluded.created_at
    """
    cur = research_conn.executemany(sql, records)
    research_conn.commit()
    written = cur.rowcount
    log.info("[sector_classifier] Wrote %d sector_data rows for %s", written, trade_date)
    return written


# ---------------------------------------------------------------------------
# 主進入點
# ---------------------------------------------------------------------------

def run_sector_classifier(
    trades_db_path: Optional[str] = None,
    research_db_path: Optional[str] = None,
    skip_freshness_check: bool = False,
) -> None:
    """完整執行流程：

    1. 從 TWSE OpenAPI 抓取產業分類 → sector_mapping
    2. freshness check：確認今日法人流向已入庫
    3. 聚合 eod_prices + eod_institution_flows → sector_data

    Args:
        trades_db_path: trades.db 路徑（預設讀環境變數 DB_PATH）
        research_db_path: research.db 路徑（預設讀 research_db.py 預設值）
        skip_freshness_check: 若 True 則跳過法人流向新鮮度檢查（用於手動補跑）
    """
    import os
    from openclaw.path_utils import get_repo_root
    from app.db.research_db import (
        RESEARCH_DB_PATH,
        connect_research,
        init_research_db,
    )

    # 解析路徑
    if trades_db_path is None:
        trades_db_path = os.environ.get(
            "DB_PATH",
            str(get_repo_root() / "data" / "sqlite" / "trades.db"),
        )
    if research_db_path is None:
        research_db_path = str(RESEARCH_DB_PATH)

    log.info("[sector_classifier] trades_db=%s research_db=%s", trades_db_path, research_db_path)

    # 確保 schema 存在
    init_research_db(Path(research_db_path))

    # 建立連線
    trades_conn = sqlite3.connect(
        f"file:{trades_db_path}?mode=ro",
        uri=True,
        check_same_thread=False,
    )
    trades_conn.row_factory = sqlite3.Row

    research_conn = connect_research(Path(research_db_path))

    try:
        # Step 1: 抓取產業分類
        log.info("[sector_classifier] Fetching TWSE company list…")
        companies = _fetch_twse_company_list()

        if companies:
            mapping_rows = build_sector_mapping(companies)
            n = store_sector_mapping(research_conn, mapping_rows)
            log.info("[sector_classifier] sector_mapping: %d rows upserted", n)
        else:
            log.warning("[sector_classifier] TWSE company list empty — using existing mapping")

        # Step 2: freshness check
        latest_date = _get_latest_trade_date(trades_conn)
        if not latest_date:
            log.warning("[sector_classifier] No trade dates in eod_prices — abort")
            return

        if not skip_freshness_check:
            if not _has_todays_institution_flow(trades_conn, latest_date):
                log.warning(
                    "[sector_classifier] eod_institution_flows not yet available for %s — skipping sector_data",
                    latest_date,
                )
                return

        # Step 3: 聚合
        n = compute_sector_data(trades_conn, research_conn, latest_date)
        log.info("[sector_classifier] Done. sector_data rows written: %d", n)

    finally:
        trades_conn.close()
        research_conn.close()
