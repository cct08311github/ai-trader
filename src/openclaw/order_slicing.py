from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Literal, Optional, Sequence, Tuple

from openclaw.position_sizing import calculate_position_qty
from openclaw.risk_engine import OrderCandidate


Side = Literal["buy", "sell"]
SlicingMethod = Literal["twap", "vwap"]


@dataclass(frozen=True)
class OrderBookLevel:
    price: float
    qty: int


@dataclass(frozen=True)
class OrderBookSnapshot:
    ts_ms: int
    bids: Sequence[OrderBookLevel]
    asks: Sequence[OrderBookLevel]


@dataclass(frozen=True)
class DepthCheck:
    ok: bool
    available_qty: int
    limit_price: float
    max_slippage_bps: float


@dataclass(frozen=True)
class OrderSlice:
    scheduled_ts_ms: int
    qty: int


@dataclass(frozen=True)
class SlicePlan:
    method: SlicingMethod
    total_qty: int
    slices: Sequence[OrderSlice]
    duration_ms: int


def _clip_int(v: int, lo: int, hi: int) -> int:
    return max(lo, min(int(v), hi))


def _sum_qty(levels: Iterable[OrderBookLevel]) -> int:
    s = 0
    for lv in levels:
        try:
            s += max(0, int(lv.qty))
        except Exception:
            continue
    return int(s)


def estimate_available_qty_within_slippage(
    *,
    side: Side,
    book: OrderBookSnapshot,
    max_slippage_bps: float,
) -> Tuple[int, float]:
    """Estimate available quantity within a max slippage band.

    For buy orders we consume asks up to best_ask*(1+slippage).
    For sell orders we consume bids down to best_bid*(1-slippage).

    Returns: (available_qty, limit_price)
    """

    if max_slippage_bps < 0:
        max_slippage_bps = 0.0

    if side == "buy":
        if not book.asks:
            return 0, 0.0
        best = float(book.asks[0].price)
        limit_price = best * (1.0 + max_slippage_bps / 10_000.0)
        levels = [lv for lv in book.asks if float(lv.price) <= limit_price]
        return _sum_qty(levels), float(limit_price)

    # sell
    if not book.bids:
        return 0, 0.0
    best = float(book.bids[0].price)
    limit_price = best * (1.0 - max_slippage_bps / 10_000.0)
    levels = [lv for lv in book.bids if float(lv.price) >= limit_price]
    return _sum_qty(levels), float(limit_price)


def check_orderbook_depth(
    *,
    side: Side,
    desired_qty: int,
    book: OrderBookSnapshot,
    max_slippage_bps: float,
    min_depth_multiplier: float = 1.20,
) -> DepthCheck:
    """Ensure the orderbook has sufficient depth for slicing/large orders.

    Rule of thumb: available_qty >= desired_qty * min_depth_multiplier.
    """

    desired_qty = max(0, int(desired_qty))
    available, limit_price = estimate_available_qty_within_slippage(
        side=side, book=book, max_slippage_bps=max_slippage_bps
    )
    ok = available >= int(desired_qty * float(min_depth_multiplier))
    return DepthCheck(ok=ok, available_qty=int(available), limit_price=float(limit_price), max_slippage_bps=float(max_slippage_bps))


def plan_twap_slices(
    *,
    total_qty: int,
    start_ts_ms: int,
    duration_ms: int,
    n_slices: int,
    min_slice_qty: int = 1,
    max_slice_qty: Optional[int] = None,
) -> SlicePlan:
    """Build a TWAP slice plan (equal qty per interval, remainder distributed)."""

    total_qty = max(0, int(total_qty))
    n_slices = max(1, int(n_slices))
    duration_ms = max(0, int(duration_ms))

    if total_qty == 0:
        return SlicePlan(method="twap", total_qty=0, slices=[], duration_ms=duration_ms)

    base = total_qty // n_slices
    rem = total_qty % n_slices

    # When total_qty < n_slices, we just emit fewer slices.
    per_slice: List[int] = []
    for i in range(n_slices):
        q = base + (1 if i < rem else 0)
        if q <= 0:
            continue
        per_slice.append(int(q))

    # Apply min/max constraints.
    # If min constraint makes total exceed, we keep total by trimming later slices.
    if min_slice_qty > 1:
        per_slice = [max(int(min_slice_qty), q) for q in per_slice]

    if max_slice_qty is not None:
        per_slice = [min(int(max_slice_qty), q) for q in per_slice]

    # Normalize back to total_qty.
    current = sum(per_slice)
    if current != total_qty:
        delta = current - total_qty
        # Reduce from the back first.
        i = len(per_slice) - 1
        while delta > 0 and i >= 0:
            can_reduce = per_slice[i] - 1
            if can_reduce > 0:
                r = min(delta, can_reduce)
                per_slice[i] -= r
                delta -= r
            i -= 1
        # If we couldn't reduce enough, we accept a small over-allocation (safe).

    interval_ms = 0 if len(per_slice) <= 1 else duration_ms // (len(per_slice) - 1)

    slices: List[OrderSlice] = []
    for i, q in enumerate(per_slice):
        slices.append(OrderSlice(scheduled_ts_ms=int(start_ts_ms + i * interval_ms), qty=int(q)))

    return SlicePlan(method="twap", total_qty=total_qty, slices=slices, duration_ms=duration_ms)


def plan_vwap_slices(
    *,
    total_qty: int,
    start_ts_ms: int,
    duration_ms: int,
    volume_profile: Sequence[int],
    min_slice_qty: int = 1,
    max_slice_qty: Optional[int] = None,
) -> SlicePlan:
    """Build a VWAP slice plan based on a volume profile.

    Parameters
    ----------
    volume_profile:
        A list of positive integers representing expected volume per interval.
        The number of slices equals len(volume_profile).
    """

    total_qty = max(0, int(total_qty))
    duration_ms = max(0, int(duration_ms))

    if total_qty == 0:
        return SlicePlan(method="vwap", total_qty=0, slices=[], duration_ms=duration_ms)

    if not volume_profile:
        # fallback to TWAP behavior
        return plan_twap_slices(
            total_qty=total_qty,
            start_ts_ms=start_ts_ms,
            duration_ms=duration_ms,
            n_slices=1,
            min_slice_qty=min_slice_qty,
            max_slice_qty=max_slice_qty,
        )

    weights = [max(0, int(v)) for v in volume_profile]
    s = sum(weights)
    if s <= 0:
        weights = [1] * len(volume_profile)
        s = len(volume_profile)

    raw = [total_qty * w / s for w in weights]
    per_slice = [int(x) for x in raw]

    # Distribute remainder to biggest fractional parts
    allocated = sum(per_slice)
    remainder = total_qty - allocated
    if remainder > 0:
        frac = [(raw[i] - per_slice[i], i) for i in range(len(per_slice))]
        frac.sort(reverse=True)
        for _, idx in frac[:remainder]:
            per_slice[idx] += 1

    # Apply constraints.
    if min_slice_qty > 1:
        per_slice = [max(int(min_slice_qty), q) for q in per_slice]
    if max_slice_qty is not None:
        per_slice = [min(int(max_slice_qty), q) for q in per_slice]

    # Normalize back down to total_qty if needed.
    current = sum(per_slice)
    if current > total_qty:
        delta = current - total_qty
        # reduce from smallest slices first
        idxs = sorted(range(len(per_slice)), key=lambda i: per_slice[i])
        for i in idxs:
            if delta <= 0:
                break
            can_reduce = per_slice[i] - 1
            if can_reduce > 0:
                r = min(delta, can_reduce)
                per_slice[i] -= r
                delta -= r

    interval_ms = 0 if len(per_slice) <= 1 else duration_ms // (len(per_slice) - 1)

    slices: List[OrderSlice] = []
    for i, q in enumerate(per_slice):
        if q <= 0:
            continue
        slices.append(OrderSlice(scheduled_ts_ms=int(start_ts_ms + i * interval_ms), qty=int(q)))

    return SlicePlan(method="vwap", total_qty=total_qty, slices=slices, duration_ms=duration_ms)


def slice_order_candidate(
    *,
    candidate: OrderCandidate,
    method: SlicingMethod,
    start_ts_ms: int,
    duration_ms: int,
    n_slices: int = 5,
    volume_profile: Optional[Sequence[int]] = None,
) -> List[OrderCandidate]:
    """Slice an OrderCandidate into multiple smaller candidates.

    Price/order_type/tif are copied as-is; qty is split.
    """

    if candidate.qty <= 0:
        return []

    if method == "vwap":
        profile = list(volume_profile) if volume_profile is not None else [1] * int(n_slices)
        plan = plan_vwap_slices(
            total_qty=candidate.qty,
            start_ts_ms=start_ts_ms,
            duration_ms=duration_ms,
            volume_profile=profile,
        )
    else:
        plan = plan_twap_slices(
            total_qty=candidate.qty,
            start_ts_ms=start_ts_ms,
            duration_ms=duration_ms,
            n_slices=int(n_slices),
        )

    out: List[OrderCandidate] = []
    for sl in plan.slices:
        out.append(
            OrderCandidate(
                symbol=candidate.symbol,
                side=candidate.side,
                qty=int(sl.qty),
                price=candidate.price,
                order_type=candidate.order_type,
                tif=candidate.tif,
                opens_new_position=candidate.opens_new_position,
            )
        )
    return out


def build_sliced_entry_plan_from_risk_inputs(
    *,
    nav: float,
    entry_price: float,
    stop_price: float,
    side: Side,
    limits: Dict[str, float],
    start_ts_ms: int,
    duration_ms: int,
    method: SlicingMethod = "twap",
    n_slices: int = 5,
    authority_level: Optional[int] = None,
    sentinel_policy_path: str = "config/sentinel_policy_v1.json",
    symbol: str = "UNKNOWN",
) -> Tuple[int, List[OrderCandidate]]:
    """Integration helper: position sizing (#5) -> sliced OrderCandidates (#19).

    Returns: (total_qty, sliced_candidates)
    """

    qty = calculate_position_qty(
        nav=float(nav),
        entry_price=float(entry_price),
        stop_price=float(stop_price),
        atr=None,
        atr_stop_multiple=float(limits.get("atr_stop_multiple", 2.0)),
        base_risk_pct=float(limits.get("max_loss_per_trade_pct_nav", 0.005)),
        confidence=float(limits.get("confidence", 1.0)),
        confidence_threshold=float(limits.get("low_confidence_threshold", 0.60)),
        low_confidence_scale=float(limits.get("low_confidence_scale", 0.50)),
        volatility_multiplier=float(limits.get("volatility_multiplier", 1.0)),
        method=str(limits.get("position_sizing_method", "fixed_fractional")),
        authority_level=authority_level,
        sentinel_policy_path=sentinel_policy_path,
    )

    if qty <= 0:
        return 0, []

    candidate = OrderCandidate(
        symbol=str(symbol),
        side=side,
        qty=int(qty),
        price=float(entry_price),
        order_type="limit",
        tif=str(limits.get("tif", "IOC")),
        opens_new_position=True,
    )

    sliced = slice_order_candidate(
        candidate=candidate,
        method=method,
        start_ts_ms=start_ts_ms,
        duration_ms=duration_ms,
        n_slices=int(n_slices),
        volume_profile=None,
    )
    return int(qty), sliced
