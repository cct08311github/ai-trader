# src/openclaw/cost_model.py
"""cost_model.py — 台股交易成本計算（純函數）

手續費：price × qty × 0.1425%（買賣雙向）
證交稅：price × qty × 0.3%（僅賣方）
T+2 交割。
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class CostParams:
    """交易成本參數 — 可調整以模擬折扣券商或政策變動。"""
    commission_rate: float = 0.001425   # 0.1425%
    tax_rate: float = 0.003            # 0.3% (sell only)
    commission_discount: float = 1.0   # 券商折扣（0.28 = 2.8 折）


def calc_buy_cost(price: float, qty: int, params: CostParams = CostParams()) -> float:
    """買入總成本 = price × qty + 手續費。"""
    notional = price * qty
    fee = notional * params.commission_rate * params.commission_discount
    return round(notional + fee, 2)


def calc_sell_proceeds(price: float, qty: int, params: CostParams = CostParams()) -> float:
    """賣出淨收入 = price × qty - 手續費 - 證交稅。"""
    notional = price * qty
    fee = notional * params.commission_rate * params.commission_discount
    tax = notional * params.tax_rate
    return round(notional - fee - tax, 2)


def calc_round_trip_pnl(
    buy_price: float,
    sell_price: float,
    qty: int,
    params: CostParams = CostParams(),
) -> float:
    """一筆完整交易的損益 = 賣出淨收入 - 買入總成本。"""
    return round(calc_sell_proceeds(sell_price, qty, params) - calc_buy_cost(buy_price, qty, params), 2)
