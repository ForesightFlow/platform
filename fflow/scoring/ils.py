"""ILS (Information Leakage Score) computation.

All arithmetic uses Decimal — no float. Prices are in [0, 1] with 6-decimal precision.

Standard ILS (event-resolved markets):
  ILS(M) = (p(T_news) - p(T_open)) / (p_resolve - p(T_open))
           when |delta_total| > epsilon (default 0.05)

Deadline ILS (deadline_resolved markets, paper Section 7):
  ILS_dl = (p(T_resolve⁻) - p(T_open)) / (p_resolve - p(T_open))
  where T_resolve⁻ = T_resolve - lookback (default 1 h)

Multi-window variants ILS_w (both modes) use the price at (T_ref - w):
  ILS_w = (p(T_ref) - p(T_ref - w)) / (p_resolve - p(T_ref - w))
  where T_ref = T_news (standard) or T_resolve⁻ (deadline).
"""

from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

import pandas as pd
from pydantic import BaseModel

_EPSILON_DEFAULT = Decimal("0.05")
_LOOKUP_TOLERANCE = timedelta(minutes=5)
_DEADLINE_LOOKBACK = timedelta(hours=1)  # T_resolve⁻ = T_resolve - 1h
# CLOB indexing lag: first trade price can appear up to 30 min after market creation.
# T_open lookup uses a forward-only window [t_open, t_open + 30min] instead of ±5 min.
_TOPEN_FORWARD_WINDOW = timedelta(minutes=30)

_WINDOWS: dict[str, timedelta] = {
    "30min": timedelta(minutes=30),
    "2h": timedelta(hours=2),
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}


class PriceLookupError(Exception):
    pass


class ILSBundle(BaseModel):
    ils: Decimal | None
    ils_30min: Decimal | None
    ils_2h: Decimal | None
    ils_6h: Decimal | None
    ils_24h: Decimal | None
    ils_7d: Decimal | None
    delta_pre: Decimal
    delta_total: Decimal
    p_open: Decimal
    p_news: Decimal
    p_resolve: int
    flags: list[str]

    model_config = {"arbitrary_types_allowed": True}


def compute_ils(
    prices: pd.DataFrame,
    t_open: datetime,
    t_news: datetime,
    t_resolve: datetime,
    p_resolve: int,
    epsilon: Decimal = _EPSILON_DEFAULT,
) -> ILSBundle:
    """Compute ILS and multi-window variants from a minute-resolution price series.

    Args:
        prices: DataFrame with columns 'ts' (tz-aware datetime) and 'mid_price' (Decimal or numeric).
        t_open: Market creation timestamp (T_open).
        t_news: First public mention timestamp (T_news).
        t_resolve: UMA resolution timestamp (T_resolve).
        p_resolve: Binary resolution outcome — 0 (NO) or 1 (YES).
        epsilon: Minimum |delta_total| for ILS to be defined. Default 0.05.

    Returns:
        ILSBundle with all computed values and any diagnostic flags.
    """
    flags: list[str] = []

    p_open = _lookup_price(prices, t_open, flags, "price_history_gap_at_topen", forward_window=_TOPEN_FORWARD_WINDOW)
    p_news = _lookup_price(prices, t_news, flags, "price_history_gap_at_tnews")

    p_resolve_dec = Decimal(str(p_resolve))
    delta_pre = p_news - p_open
    delta_total = p_resolve_dec - p_open

    # ILS undefined when market barely moved
    if abs(delta_total) < epsilon:
        flags.append("low_information_market")
        ils = None
    else:
        ils = _div(delta_pre, delta_total)

    # Multi-window variants
    window_results: dict[str, Decimal | None] = {}
    for name, width in _WINDOWS.items():
        ref_time = t_news - width
        if ref_time < t_open:
            flags.append(f"window_{name}_predates_topen")
            window_results[name] = None
            continue
        try:
            p_ref = _lookup_price(prices, ref_time, [], "")
        except PriceLookupError:
            flags.append(f"price_history_gap_window_{name}")
            window_results[name] = None
            continue

        d_total_w = p_resolve_dec - p_ref
        if abs(d_total_w) < epsilon:
            window_results[name] = None
        else:
            window_results[name] = _div(p_news - p_ref, d_total_w)

    return ILSBundle(
        ils=ils,
        ils_30min=window_results["30min"],
        ils_2h=window_results["2h"],
        ils_6h=window_results["6h"],
        ils_24h=window_results["24h"],
        ils_7d=window_results["7d"],
        delta_pre=delta_pre,
        delta_total=delta_total,
        p_open=p_open,
        p_news=p_news,
        p_resolve=p_resolve,
        flags=flags,
    )


def _lookup_price(
    prices: pd.DataFrame,
    ts: datetime,
    flags: list[str],
    flag_name: str,
    forward_window: timedelta | None = None,
) -> Decimal:
    """Return the price nearest to ts.

    Default mode: nearest price within ±5 min (symmetric).
    When forward_window is set: first price in [ts, ts + forward_window].
    Used for t_open lookups to accommodate CLOB indexing lag (~20 min typical).
    """
    if prices.empty:
        raise PriceLookupError(f"Empty price series, cannot look up {ts}")

    ts_utc = ts.astimezone(UTC) if ts.tzinfo else ts.replace(tzinfo=UTC)
    ts_snapped = ts_utc.replace(second=0, microsecond=0)

    col = prices["ts"]
    if hasattr(col.dtype, "tz") and col.dtype.tz is not None:
        ts_series = col
    else:
        ts_series = pd.to_datetime(col, utc=True)

    if forward_window is not None:
        ts_end = pd.Timestamp(ts_snapped + forward_window)
        mask = (ts_series >= pd.Timestamp(ts_snapped)) & (ts_series <= ts_end)
        candidates = prices[mask]
        if candidates.empty:
            if flag_name:
                flags.append(flag_name)
            raise PriceLookupError(
                f"No price in [{ts_snapped}, +{forward_window}]: window is empty"
            )
        idx = ts_series[mask].idxmin()
    else:
        diffs = (ts_series - pd.Timestamp(ts_snapped)).abs()
        idx = diffs.idxmin()
        min_diff = diffs[idx]
        if min_diff > pd.Timedelta(_LOOKUP_TOLERANCE):
            if flag_name:
                flags.append(flag_name)
            raise PriceLookupError(
                f"No price within ±5 min of {ts_snapped}: nearest gap is {min_diff}"
            )

    raw = prices.loc[idx, "mid_price"]
    try:
        return Decimal(str(raw))
    except InvalidOperation:
        raise PriceLookupError(f"Cannot convert price {raw!r} to Decimal")


def _div(numerator: Decimal, denominator: Decimal) -> Decimal:
    return (numerator / denominator).quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN)


def compute_ils_deadline(
    prices: pd.DataFrame,
    t_open: datetime,
    t_resolve: datetime,
    p_resolve: int,
    epsilon: Decimal = _EPSILON_DEFAULT,
    lookback: timedelta = _DEADLINE_LOOKBACK,
) -> ILSBundle:
    """Compute deadline-ILS (paper Section 7) from a minute-resolution price series.

    ILS_dl = (p(T_resolve⁻) - p(T_open)) / (p_resolve - p(T_open))

    T_resolve⁻ = T_resolve - lookback (default 1 h). For markets that resolve
    before their stated deadline, T_resolve is the actual resolution time.

    Returns the same ILSBundle shape as compute_ils() for DB compatibility.
    The 'p_news' field stores p(T_resolve⁻) — the pre-deadline reference price.
    Multi-window variants measure price movement relative to T_resolve⁻.

    Args:
        prices:    DataFrame with 'ts' (tz-aware) and 'mid_price' columns.
        t_open:    Market creation timestamp (T_open).
        t_resolve: Market resolution timestamp (T_resolve).
        p_resolve: Binary resolution outcome — 0 (NO) or 1 (YES).
        epsilon:   Minimum |delta_total| for ILS to be defined. Default 0.05.
        lookback:  Window before T_resolve defining T_resolve⁻. Default 1 h.
    """
    flags: list[str] = []

    p_open = _lookup_price(prices, t_open, flags, "price_history_gap_at_topen", forward_window=_TOPEN_FORWARD_WINDOW)

    t_event_minus = t_resolve - lookback
    if t_event_minus <= t_open:
        flags.append("lookback_predates_topen")
        t_event_minus = t_open  # fallback: use open price as both endpoints

    p_event_minus = _lookup_price(
        prices, t_event_minus, flags, "price_history_gap_at_tevent_minus"
    )

    p_resolve_dec = Decimal(str(p_resolve))
    delta_pre = p_event_minus - p_open
    delta_total = p_resolve_dec - p_open

    if abs(delta_total) < epsilon:
        flags.append("low_information_market")
        ils = None
    else:
        ils = _div(delta_pre, delta_total)

    # Multi-window variants — relative to t_event_minus as reference point
    window_results: dict[str, Decimal | None] = {}
    for name, width in _WINDOWS.items():
        ref_time = t_event_minus - width
        if ref_time < t_open:
            flags.append(f"window_{name}_predates_topen")
            window_results[name] = None
            continue
        try:
            p_ref = _lookup_price(prices, ref_time, [], "")
        except PriceLookupError:
            flags.append(f"price_history_gap_window_{name}")
            window_results[name] = None
            continue
        d_total_w = p_resolve_dec - p_ref
        if abs(d_total_w) < epsilon:
            window_results[name] = None
        else:
            window_results[name] = _div(p_event_minus - p_ref, d_total_w)

    return ILSBundle(
        ils=ils,
        ils_30min=window_results["30min"],
        ils_2h=window_results["2h"],
        ils_6h=window_results["6h"],
        ils_24h=window_results["24h"],
        ils_7d=window_results["7d"],
        delta_pre=delta_pre,
        delta_total=delta_total,
        p_open=p_open,
        p_news=p_event_minus,  # stores T_resolve⁻ price for deadline markets
        p_resolve=p_resolve,
        flags=flags,
    )
