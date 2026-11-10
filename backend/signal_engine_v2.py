from __future__ import annotations

from typing import Any, Optional

from signal_engine import (
    TIMEFRAME_SECONDS,
    analyse_timeframe,
    calculate_atr,
    calculate_ema,
    calculate_rsi,
)


TIMEFRAMES = ("1D", "4H", "1H", "15M", "5M")


def _closed_candles(
    candles: list[dict[str, Any]],
    timeframe: str,
    as_of_epoch: int,
) -> list[dict[str, Any]]:
    """Return sorted, unique candles that had fully closed by as_of_epoch."""
    duration = TIMEFRAME_SECONDS[timeframe]
    unique: dict[int, dict[str, Any]] = {}

    for candle in candles:
        epoch = int(candle["epoch"])
        if epoch + duration <= as_of_epoch:
            unique[epoch] = candle

    return [unique[epoch] for epoch in sorted(unique)]


def _wait(timeframe: str, reason: str, **extra: Any) -> dict[str, Any]:
    return {
        "timeframe": timeframe,
        "signal": "WAIT",
        "qualified": False,
        "reason": reason,
        **extra,
    }


def _trend_context(
    candles: list[dict[str, Any]],
    timeframe: str,
    as_of_epoch: int,
) -> dict[str, Any]:
    closed = _closed_candles(candles, timeframe, as_of_epoch)

    if len(closed) < 50:
        return {
            "timeframe": timeframe,
            "trend": "NEUTRAL",
            "ready": False,
            "reason": "At least 50 fully closed candles are required.",
            "closed_candles": len(closed),
        }

    closes = [float(c["close"]) for c in closed]
    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)
    rsi = calculate_rsi(closes)
    atr = calculate_atr(closed)

    if None in (ema20, ema50, rsi, atr) or not atr or atr <= 0:
        return {
            "timeframe": timeframe,
            "trend": "NEUTRAL",
            "ready": False,
            "reason": "Trend indicators are unavailable.",
            "closed_candles": len(closed),
        }

    last_close = closes[-1]
    if ema20 > ema50 and last_close > ema20 and rsi >= 50:
        trend = "BULLISH"
    elif ema20 < ema50 and last_close < ema20 and rsi <= 50:
        trend = "BEARISH"
    else:
        trend = "NEUTRAL"

    return {
        "timeframe": timeframe,
        "trend": trend,
        "ready": True,
        "close": last_close,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi,
        "atr": atr,
        "closed_candles": len(closed),
        "candle_epoch": int(closed[-1]["epoch"]),
    }


def _detect_15m_setup(
    candles: list[dict[str, Any]],
    as_of_epoch: int,
    direction: str,
) -> dict[str, Any]:
    closed = _closed_candles(candles, "15M", as_of_epoch)

    if len(closed) < 30:
        return {
            "qualified": False,
            "reason": "At least 30 fully closed 15M candles are required.",
            "closed_candles": len(closed),
        }

    closes = [float(c["close"]) for c in closed]
    atr = calculate_atr(closed)

    if atr is None or atr <= 0:
        return {"qualified": False, "reason": "15M setup indicators are unavailable."}

    latest = closed[-1]
    latest_open = float(latest["open"])
    latest_close = float(latest["close"])

    confirmation = (
        latest_close > latest_open if direction == "BUY"
        else latest_close < latest_open
    )

    setup_type = "NONE"
    pullback = False
    liquidity_sweep = False
    setup_epoch = None

    # Inspect the three completed candles before the latest confirmation candle.
    for index in range(len(closed) - 2, max(len(closed) - 5, 4) - 1, -1):
        candidate = closed[index]
        prior = closed[index - 5:index]

        if len(prior) < 5:
            continue

        candidate_ema = calculate_ema(closes[:index + 1], 20)
        if candidate_ema is None:
            continue

        high = float(candidate["high"])
        low = float(candidate["low"])
        close = float(candidate["close"])
        prior_low = min(float(c["low"]) for c in prior)
        prior_high = max(float(c["high"]) for c in prior)

        if direction == "BUY":
            candidate_pullback = (
                low <= candidate_ema + 0.25 * atr and close > candidate_ema
            )
            candidate_sweep = low < prior_low and close > prior_low
        else:
            candidate_pullback = (
                high >= candidate_ema - 0.25 * atr and close < candidate_ema
            )
            candidate_sweep = high > prior_high and close < prior_high

        if candidate_sweep or candidate_pullback:
            liquidity_sweep = candidate_sweep
            pullback = candidate_pullback
            setup_type = (
                "LIQUIDITY_SWEEP_RECLAIM" if direction == "BUY"
                else "LIQUIDITY_SWEEP_REJECTION"
            ) if candidate_sweep else "EMA20_PULLBACK"
            setup_epoch = int(candidate["epoch"])
            break

    setup_found = pullback or liquidity_sweep
    qualified = setup_found and confirmation

    if not setup_found:
        reason = "No 15M pullback or liquidity sweep found in the last three setup candles."
    elif not confirmation:
        reason = "15M setup found, but the latest candle has not confirmed the direction."
    else:
        reason = "15M setup found and latest candle confirmed the direction."

    return {
        "qualified": qualified,
        "setup": setup_type,
        "pullback": pullback,
        "liquidity_sweep": liquidity_sweep,
        "confirmation_candle": confirmation,
        "setup_candle_epoch": setup_epoch,
        "candle_epoch": int(latest["epoch"]),
        "atr": atr,
        "reason": reason,
    }


def _confirm_5m(
    candles: list[dict[str, Any]],
    as_of_epoch: int,
    direction: str,
) -> dict[str, Any]:
    closed = _closed_candles(candles, "5M", as_of_epoch)

    if len(closed) < 30:
        return {
            "qualified": False,
            "reason": "At least 30 fully closed 5M candles are required.",
            "closed_candles": len(closed),
        }

    latest = closed[-1]
    previous = closed[-2]
    closes = [float(c["close"]) for c in closed]
    ema9 = calculate_ema(closes, 9)
    ema21 = calculate_ema(closes, 21)
    rsi = calculate_rsi(closes)
    atr = calculate_atr(closed)

    if None in (ema9, ema21, rsi, atr) or not atr or atr <= 0:
        return {"qualified": False, "reason": "5M confirmation indicators are unavailable."}

    if direction == "BUY":
        checks = {
            "ema_alignment": ema9 > ema21,
            "price_above_ema9": float(latest["close"]) > ema9,
            "bullish_momentum": closes[-1] > closes[-4],
            "rsi_confirmation": 50 <= rsi <= 72,
            "bullish_candle_break": (
                float(latest["close"]) > float(latest["open"])
                and float(latest["close"]) > float(previous["high"])
            ),
        }
    else:
        checks = {
            "ema_alignment": ema9 < ema21,
            "price_below_ema9": float(latest["close"]) < ema9,
            "bearish_momentum": closes[-1] < closes[-4],
            "rsi_confirmation": 28 <= rsi <= 50,
            "bearish_candle_break": (
                float(latest["close"]) < float(latest["open"])
                and float(latest["close"]) < float(previous["low"])
            ),
        }

    passed = sum(bool(value) for value in checks.values())
    qualified = passed >= 4

    return {
        "qualified": qualified,
        "checks": checks,
        "checks_passed": passed,
        "checks_required": 4,
        "rsi": rsi,
        "atr": atr,
        "ema9": ema9,
        "ema21": ema21,
        "candle_epoch": int(latest["epoch"]),
        "close": float(latest["close"]),
        "reason": "5M entry confirmation passed." if qualified else "5M entry confirmation did not pass.",
    }


def analyse_precision_opportunity(
    candles_by_timeframe: dict[str, list[dict[str, Any]]],
    as_of_epoch: int,
) -> dict[str, Any]:
    """
    Evaluate the RevAI Precision Engine V2 at a historical or live timestamp.

    Required inputs: 4H, 1H, 15M and 5M candle arrays.
    1D is optional context only and is not a mandatory direction filter.
    Only fully closed candles are considered at as_of_epoch.
    """
    missing = [
        tf for tf in ("4H", "1H", "15M", "5M")
        if tf not in candles_by_timeframe
    ]
    if missing:
        return _wait(
            "PRECISION",
            "Missing timeframe candle data.",
            missing_timeframes=missing,
            as_of_epoch=as_of_epoch,
        )

    context_4h = _trend_context(candles_by_timeframe["4H"], "4H", as_of_epoch)
    context_1h = _trend_context(candles_by_timeframe["1H"], "1H", as_of_epoch)

    if not context_4h["ready"] or not context_1h["ready"]:
        return _wait(
            "PRECISION",
            "Higher-timeframe trend context is not ready.",
            context={"4H": context_4h, "1H": context_1h},
            as_of_epoch=as_of_epoch,
        )

    trend_4h = context_4h["trend"]
    trend_1h = context_1h["trend"]

    if trend_4h == "NEUTRAL" or trend_1h == "NEUTRAL":
        return _wait(
            "PRECISION",
            "4H or 1H trend is neutral; no trade.",
            context={"4H": context_4h, "1H": context_1h},
            as_of_epoch=as_of_epoch,
        )

    if trend_4h != trend_1h:
        return _wait(
            "PRECISION",
            "4H and 1H trends are not aligned.",
            context={"4H": context_4h, "1H": context_1h},
            as_of_epoch=as_of_epoch,
        )

    direction = "BUY" if trend_4h == "BULLISH" else "SELL"

    setup_15m = _detect_15m_setup(
        candles_by_timeframe["15M"], as_of_epoch, direction
    )
    if not setup_15m["qualified"]:
        return _wait(
            "PRECISION",
            setup_15m["reason"],
            direction_bias=direction,
            context={"4H": context_4h, "1H": context_1h},
            setup_15m=setup_15m,
            as_of_epoch=as_of_epoch,
        )

    confirmation_5m = _confirm_5m(
        candles_by_timeframe["5M"], as_of_epoch, direction
    )
    if not confirmation_5m["qualified"]:
        return _wait(
            "PRECISION",
            confirmation_5m["reason"],
            direction_bias=direction,
            context={"4H": context_4h, "1H": context_1h},
            setup_15m=setup_15m,
            confirmation_5m=confirmation_5m,
            as_of_epoch=as_of_epoch,
        )

    entry = confirmation_5m["close"]
    atr = confirmation_5m["atr"]

    # Structure-based protective stop: recent 5M swing, with a small ATR
    # buffer. Reject an unusually wide stop rather than forcing a trade.
    five_minute_closed = _closed_candles(
        candles_by_timeframe["5M"], "5M", as_of_epoch
    )
    recent = five_minute_closed[-6:]

    if direction == "BUY":
        stop_loss = min(float(c["low"]) for c in recent) - 0.1 * atr
        risk = entry - stop_loss
    else:
        stop_loss = max(float(c["high"]) for c in recent) + 0.1 * atr
        risk = stop_loss - entry

    if risk <= 0 or risk > 2.5 * atr:
        return _wait(
            "PRECISION",
            "5M structure stop is invalid or wider than 2.5 ATR.",
            direction_bias=direction,
            entry=round(entry, 2),
            stop_loss=round(stop_loss, 2),
            risk=round(risk, 4),
            atr=round(atr, 4),
            context={"4H": context_4h, "1H": context_1h},
            setup_15m=setup_15m,
            confirmation_5m=confirmation_5m,
            as_of_epoch=as_of_epoch,
        )

    # V2 requires at least 1.5R to TP2. TP1/TP2/TP3 remain fixed R targets.
    if direction == "BUY":
        targets = [entry + risk, entry + 1.5 * risk, entry + 2.0 * risk]
    else:
        targets = [entry - risk, entry - 1.5 * risk, entry - 2.0 * risk]

    daily_context = None
    if "1D" in candles_by_timeframe:
        daily_context = _trend_context(
            candles_by_timeframe["1D"], "1D", as_of_epoch
        )

    return {
        "timeframe": "PRECISION",
        "strategy": "RevAI Gold Precision Engine V2",
        "signal": direction,
        "qualified": True,
        "reason": "4H and 1H aligned; 15M setup and 5M confirmation passed.",
        "as_of_epoch": as_of_epoch,
        "entry": round(entry, 2),
        "stop_loss": round(stop_loss, 2),
        "tp1": round(targets[0], 2),
        "tp2": round(targets[1], 2),
        "tp3": round(targets[2], 2),
        "risk_price": round(risk, 4),
        "reward_risk_tp2": 1.5,
        "context": {
            "4H": context_4h,
            "1H": context_1h,
            "1D_optional": daily_context,
        },
        "setup_15m": setup_15m,
        "confirmation_5m": confirmation_5m,
        "execution_timeframe": "5M",
    }


def analyse_v2_dashboard(
    candles_by_timeframe: dict[str, list[dict[str, Any]]],
    as_of_epoch: int,
) -> dict[str, Any]:
    """
    Return five independent timeframe cards plus the combined V2 opportunity.

    The five independent cards deliberately retain the existing V1 scanner
    logic for a baseline comparison. The combined Precision result is V2.
    """
    independent: dict[str, dict[str, Any]] = {}

    for timeframe in TIMEFRAMES:
        candles = candles_by_timeframe.get(timeframe, [])
        independent[timeframe] = analyse_timeframe(
            candles,
            timeframe,
            as_of_epoch=as_of_epoch,
        )

    precision = analyse_precision_opportunity(
        candles_by_timeframe,
        as_of_epoch,
    )

    return {
        "symbol": "frxXAUUSD",
        "strategy": "RevAI Gold Precision Engine V2",
        "as_of_epoch": as_of_epoch,
        "independent_timeframe_signals": independent,
        "precision_opportunity": precision,
        "note": (
            "Independent timeframe cards use the existing V1 signal rules "
            "for comparison; the combined Precision opportunity uses V2 "
            "multi-timeframe confirmation."
        ),
    }
