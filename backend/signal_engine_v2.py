from __future__ import annotations

from typing import Any

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
    direction: str | None = None,
) -> dict[str, Any]:
    """
    Apply ALPHA BOT's 15M five-condition scanner.
    A direction qualifies at 4/5 only when it leads the opposite score.
    """
    result = analyse_timeframe(candles, "15M", as_of_epoch=as_of_epoch)
    analysis = result.get("analysis", {})
    detected = result.get("signal", "WAIT")

    if direction and detected != direction:
        return {
            **result,
            "qualified": False,
            "reason": (
                f"15M scanner returned {detected}; it does not confirm "
                f"the {direction} higher-timeframe bias."
            ),
        }

    return {
        **result,
        "qualified": detected in ("BUY", "SELL"),
        "setup": "15M_4_OF_5_CONFIRMATION",
        "analysis": analysis,
        "candle_epoch": (
            int(result.get("analysis", {}).get("candle_epoch", 0))
            if result.get("analysis") else None
        ),
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




def _bollinger_bands(closes: list[float], period: int = 20, deviations: float = 2.0):
    """Population-standard-deviation Bollinger Bands using closed candles only."""
    if len(closes) < period:
        return None
    window = closes[-period:]
    middle = sum(window) / period
    variance = sum((value - middle) ** 2 for value in window) / period
    stddev = variance ** 0.5
    return {
        "middle": middle,
        "upper": middle + deviations * stddev,
        "lower": middle - deviations * stddev,
        "period": period,
        "deviations": deviations,
    }


def _candle_pattern(latest: dict[str, Any], previous: dict[str, Any] | None):
    """Conservative closed-candle pattern recognition."""
    o, h, low, c = (float(latest[k]) for k in ("open", "high", "low", "close"))
    body = abs(c - o)
    span = max(h - low, 1e-12)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - low
    bullish_pin = lower_wick >= max(body * 2.0, span * 0.45) and upper_wick <= span * 0.30 and c > o
    bearish_pin = upper_wick >= max(body * 2.0, span * 0.45) and lower_wick <= span * 0.30 and c < o
    bullish_engulf = bearish_engulf = False
    if previous:
        po, pc = float(previous["open"]), float(previous["close"])
        bullish_engulf = pc < po and c > o and o <= pc and c >= po
        bearish_engulf = pc > po and c < o and o >= pc and c <= po

    bullish = bullish_pin or bullish_engulf
    bearish = bearish_pin or bearish_engulf
    names = []
    if bullish_pin:
        names.append("BULLISH_PIN_BAR")
    if bearish_pin:
        names.append("BEARISH_PIN_BAR")
    if bullish_engulf:
        names.append("BULLISH_ENGULFING")
    if bearish_engulf:
        names.append("BEARISH_ENGULFING")
    return {
        "bullish": bullish,
        "bearish": bearish,
        "patterns": names,
        "body": body,
        "range": span,
        "upper_wick": upper_wick,
        "lower_wick": lower_wick,
    }


def _level_proximity(
    closed: list[dict[str, Any]], price: float, atr: float, lookback: int = 60
):
    """Approximate horizontal levels from recent swing highs/lows."""
    sample = closed[-lookback:]
    highs = [float(c["high"]) for c in sample]
    lows = [float(c["low"]) for c in sample]
    swing_highs = [
        highs[i] for i in range(1, len(highs) - 1)
        if highs[i] >= highs[i - 1] and highs[i] > highs[i + 1]
    ]
    swing_lows = [
        lows[i] for i in range(1, len(lows) - 1)
        if lows[i] <= lows[i - 1] and lows[i] < lows[i + 1]
    ]
    tolerance = max(atr * 0.35, abs(price) * 0.00015)
    nearest_resistance = min(swing_highs, key=lambda x: abs(x - price)) if swing_highs else None
    nearest_support = min(swing_lows, key=lambda x: abs(x - price)) if swing_lows else None
    support_near = nearest_support is not None and abs(price - nearest_support) <= tolerance
    resistance_near = nearest_resistance is not None and abs(price - nearest_resistance) <= tolerance
    return {
        "support": round(nearest_support, 5) if nearest_support is not None else None,
        "resistance": round(nearest_resistance, 5) if nearest_resistance is not None else None,
        "support_near": support_near,
        "resistance_near": resistance_near,
        "tolerance": round(tolerance, 5),
    }


def _timeframe_confluences(
    candles: list[dict[str, Any]], timeframe: str, as_of_epoch: int
):
    closed = _closed_candles(candles, timeframe, as_of_epoch)
    if len(closed) < 22:
        return {
            "timeframe": timeframe, "ready": False,
            "reason": "At least 22 fully closed candles are required for Bollinger analysis.",
        }
    latest = closed[-1]
    previous = closed[-2]
    closes = [float(c["close"]) for c in closed]
    atr = calculate_atr(closed)
    bands = _bollinger_bands(closes)
    if not atr or atr <= 0 or not bands:
        return {"timeframe": timeframe, "ready": False, "reason": "Indicators unavailable."}

    price = float(latest["close"])
    pattern = _candle_pattern(latest, previous)
    levels = _level_proximity(closed, price, float(atr))
    # A band interaction requires a wick touch/penetration; a close outside
    # followed by a close back inside is separately identified as a re-entry.
    lower_touch = float(latest["low"]) <= bands["lower"]
    upper_touch = float(latest["high"]) >= bands["upper"]
    lower_reentry = lower_touch and price > bands["lower"]
    upper_reentry = upper_touch and price < bands["upper"]

    bullish_level_rejection = pattern["bullish"] and levels["support_near"]
    bearish_level_rejection = pattern["bearish"] and levels["resistance_near"]
    bullish_band_rejection = pattern["bullish"] and lower_touch
    bearish_band_rejection = pattern["bearish"] and upper_touch

    bullish_score = sum((
        bool(pattern["bullish"]),
        bool(levels["support_near"]),
        bool(lower_touch),
        bool(lower_reentry),
    ))
    bearish_score = sum((
        bool(pattern["bearish"]),
        bool(levels["resistance_near"]),
        bool(upper_touch),
        bool(upper_reentry),
    ))
    return {
        "timeframe": timeframe,
        "ready": True,
        "candle_epoch": int(latest["epoch"]),
        "close": round(price, 5),
        "atr": round(float(atr), 5),
        "bollinger": {k: round(v, 5) if isinstance(v, float) else v for k, v in bands.items()},
        "pattern": pattern["patterns"],
        "bullish_reversal_candle": pattern["bullish"],
        "bearish_reversal_candle": pattern["bearish"],
        "levels": levels,
        "bollinger_touch": {"lower": lower_touch, "upper": upper_touch},
        "bollinger_reentry": {"from_lower": lower_reentry, "from_upper": upper_reentry},
        "bullish_level_rejection": bullish_level_rejection,
        "bearish_level_rejection": bearish_level_rejection,
        "bullish_band_rejection": bullish_band_rejection,
        "bearish_band_rejection": bearish_band_rejection,
        "bullish_confluence_score": bullish_score,
        "bearish_confluence_score": bearish_score,
    }





def _adx_series(candles: list[dict[str, Any]], period: int = 14) -> list[float]:
    """Return a simple rolling ADX series from completed OHLC candles."""
    if len(candles) < (2 * period + 1):
        return []

    true_ranges: list[float] = []
    plus_dm: list[float] = []
    minus_dm: list[float] = []

    for index in range(1, len(candles)):
        current = candles[index]
        previous = candles[index - 1]
        high_move = float(current["high"]) - float(previous["high"])
        low_move = float(previous["low"]) - float(current["low"])

        true_ranges.append(max(
            float(current["high"]) - float(current["low"]),
            abs(float(current["high"]) - float(previous["close"])),
            abs(float(current["low"]) - float(previous["close"])),
        ))
        plus_dm.append(high_move if high_move > low_move and high_move > 0 else 0.0)
        minus_dm.append(low_move if low_move > high_move and low_move > 0 else 0.0)

    dx_values: list[float] = []
    for end in range(period, len(true_ranges) + 1):
        start = end - period
        tr_sum = sum(true_ranges[start:end])
        if tr_sum <= 0:
            dx_values.append(0.0)
            continue

        plus_di = 100.0 * sum(plus_dm[start:end]) / tr_sum
        minus_di = 100.0 * sum(minus_dm[start:end]) / tr_sum
        denominator = plus_di + minus_di
        dx_values.append(
            100.0 * abs(plus_di - minus_di) / denominator
            if denominator > 0 else 0.0
        )

    adx_values: list[float] = []
    for end in range(period, len(dx_values) + 1):
        adx_values.append(sum(dx_values[end - period:end]) / period)
    return adx_values


def _bollinger_width_series(
    closes: list[float], period: int = 20
) -> list[float]:
    """Return normalised Bollinger bandwidth values for squeeze detection."""
    widths: list[float] = []
    if len(closes) < period:
        return widths

    for end in range(period, len(closes) + 1):
        window = closes[end - period:end]
        mean = sum(window) / period
        if mean == 0:
            widths.append(0.0)
            continue
        variance = sum((value - mean) ** 2 for value in window) / period
        widths.append((4.0 * variance ** 0.5) / abs(mean))
    return widths


def _assess_range_breakout(
    candles_by_timeframe: dict[str, list[dict[str, Any]]],
    direction: str,
    as_of_epoch: int,
) -> dict[str, Any]:
    """
    Define the range on completed 4H candles and assess confirmation on 1H.
    The 4H and Daily context is deliberately cut off before the candidate
    1H candle opens to avoid look-ahead in live analysis and backtests.
    """
    four_hour_all = _closed_candles(
        candles_by_timeframe.get("4H", []), "4H", as_of_epoch
    )
    one_hour = _closed_candles(
        candles_by_timeframe.get("1H", []), "1H", as_of_epoch
    )

    if len(one_hour) < 30:
        return {
            "ready": False,
            "status": "NOT_READY",
            "reason": "At least 30 fully closed 1H candles are required.",
            "range_timeframe": "4H",
            "confirmation_timeframe": "1H",
        }

    latest = one_hour[-1]
    candidate_start = int(latest["epoch"])
    # Only 4H candles that were complete before this 1H candle began are
    # eligible to define the range.
    four_hour = [
        candle for candle in four_hour_all
        if int(candle["epoch"]) + TIMEFRAME_SECONDS["4H"] <= candidate_start
    ]

    lookback = 20
    if len(four_hour) < lookback:
        return {
            "ready": False,
            "status": "NOT_READY",
            "reason": "At least 20 completed 4H candles preceding the 1H test are required.",
            "range_timeframe": "4H",
            "confirmation_timeframe": "1H",
            "completed_4h_candles": len(four_hour),
        }

    # A missing 4H interval makes the range boundaries unreliable.
    range_sample = four_hour[-lookback:]
    range_contiguous = all(
        int(current["epoch"]) - int(previous["epoch"]) == TIMEFRAME_SECONDS["4H"]
        for previous, current in zip(range_sample, range_sample[1:])
    )
    if not range_contiguous:
        return {
            "ready": False,
            "status": "NOT_READY",
            "reason": "A gap exists in the 4H range window.",
            "range_timeframe": "4H",
            "confirmation_timeframe": "1H",
            "range_data_contiguous": False,
        }

    atr_4h = calculate_atr(four_hour)
    if not atr_4h or atr_4h <= 0:
        return {
            "ready": False,
            "status": "NOT_READY",
            "reason": "4H ATR is unavailable for range qualification.",
            "range_timeframe": "4H",
            "confirmation_timeframe": "1H",
        }

    range_high = max(float(candle["high"]) for candle in range_sample)
    range_low = min(float(candle["low"]) for candle in range_sample)
    range_width = range_high - range_low
    range_width_atr = range_width / float(atr_4h)
    touch_tolerance = max(float(atr_4h) * 0.35, abs(range_high) * 0.00002)

    def count_separated_touches(side: str) -> int:
        # Consecutive candles at one boundary count as a single visit.
        # Require two intervening candles before counting a new test.
        clusters = 0
        last_touch_index = -10
        for index, candle in enumerate(range_sample):
            touched = (
                float(candle["high"]) >= range_high - touch_tolerance
                if side == "RESISTANCE"
                else float(candle["low"]) <= range_low + touch_tolerance
            )
            if touched and index - last_touch_index >= 3:
                clusters += 1
            if touched:
                last_touch_index = index
        return clusters

    resistance_touches = count_separated_touches("RESISTANCE")
    support_touches = count_separated_touches("SUPPORT")

    h4_closes = [float(candle["close"]) for candle in four_hour]
    h4_adx_values = _adx_series(four_hour)
    adx_4h = h4_adx_values[-1] if h4_adx_values else None

    ema20 = calculate_ema(h4_closes, 20)
    ema50 = calculate_ema(h4_closes, 50)
    ema20_previous = (
        calculate_ema(h4_closes[:-5], 20)
        if len(h4_closes) >= 25 else None
    )
    flat_moving_averages = bool(
        ema20 is not None
        and ema50 is not None
        and ema20_previous is not None
        and abs(ema20 - ema50) <= 0.60 * float(atr_4h)
        and abs(ema20 - ema20_previous) <= 0.40 * float(atr_4h)
    )

    bandwidths = _bollinger_width_series(h4_closes)
    bb_narrowing = bool(
        len(bandwidths) >= 5
        and bandwidths[-1] <= (
            sum(bandwidths[-5:-1]) / 4.0
        ) * 0.90
    )
    low_range_expansion = 2.0 <= range_width_atr <= 8.5
    compression_present = bb_narrowing or low_range_expansion
    low_adx = adx_4h is not None and adx_4h < 25.0

    range_qualified = (
        support_touches >= 2
        and resistance_touches >= 2
        and compression_present
        and (low_adx or flat_moving_averages)
    )

    base_diagnostics = {
        "range_timeframe": "4H",
        "confirmation_timeframe": "1H",
        "range_high": round(range_high, 5),
        "range_low": round(range_low, 5),
        "range_width_atr": round(range_width_atr, 3),
        "range_candles": lookback,
        "support_touches": int(support_touches),
        "resistance_touches": int(resistance_touches),
        "touch_tolerance": round(touch_tolerance, 5),
        "atr_4h": round(float(atr_4h), 5),
        "adx_4h": round(adx_4h, 2) if adx_4h is not None else None,
        "low_adx": bool(low_adx),
        "flat_moving_averages": bool(flat_moving_averages),
        "bollinger_narrowing": bool(bb_narrowing),
        "compression_present": bool(compression_present),
        "range_qualified": bool(range_qualified),
        "range_data_contiguous": True,
        "range_as_of_epoch": candidate_start,
    }

    if not range_qualified:
        return {
            "ready": True,
            "status": "RANGE_NOT_QUALIFIED",
            "reason": "The 4H structure does not meet the range qualification rules.",
            **base_diagnostics,
        }

    atr_1h = calculate_atr(one_hour)
    if not atr_1h or atr_1h <= 0:
        return {
            "ready": True,
            "status": "NOT_READY",
            "reason": "1H ATR is unavailable for breakout confirmation.",
            **base_diagnostics,
        }

    one_hour_adx_values = _adx_series(one_hour)
    adx_1h = one_hour_adx_values[-1] if one_hour_adx_values else None
    previous_adx_1h = (
        one_hour_adx_values[-2] if len(one_hour_adx_values) >= 2 else None
    )
    earlier_adx_1h = (
        one_hour_adx_values[-3] if len(one_hour_adx_values) >= 3 else None
    )
    adx_rising = bool(
        adx_1h is not None
        and previous_adx_1h is not None
        and adx_1h > previous_adx_1h
    )
    adx_crossed_25 = bool(
        adx_1h is not None
        and previous_adx_1h is not None
        and previous_adx_1h < 25.0 <= adx_1h
        and adx_rising
    )
    adx_rising_above_25 = bool(
        adx_1h is not None and adx_1h >= 25.0 and adx_rising
    )
    adx_expanded_from_below_20 = bool(
        adx_1h is not None
        and earlier_adx_1h is not None
        and earlier_adx_1h < 20.0
        and adx_1h >= 25.0
        and adx_rising
    )

    # Higher-timeframe direction is evaluated strictly before the candidate
    # 1H breakout candle, so its own move cannot manufacture agreement.
    pre_breakout_context = {}
    for timeframe in ("1D", "4H"):
        pre_breakout_context[timeframe] = _trend_context(
            candles_by_timeframe.get(timeframe, []),
            timeframe,
            candidate_start,
        )

    relevant_trends = [
        item.get("trend")
        for item in pre_breakout_context.values()
        if item.get("ready")
    ]
    opposing_trend = (
        "BEARISH" if direction == "BUY" else "BULLISH"
    )
    higher_timeframe_opposed = any(
        trend == opposing_trend for trend in relevant_trends
    )
    higher_timeframe_not_opposing = bool(
        relevant_trends and not higher_timeframe_opposed
    )

    close = float(latest["close"])
    open_price = float(latest["open"])
    high = float(latest["high"])
    low = float(latest["low"])
    candle_range = max(high - low, 1e-12)
    body = abs(close - open_price)
    upper_wick = high - max(open_price, close)
    lower_wick = min(open_price, close) - low
    breakout_buffer = max(float(atr_1h) * 0.10, abs(close) * 0.00001)

    def breakout_side(candle: dict[str, Any]) -> str | None:
        candle_close = float(candle["close"])
        if candle_close > range_high + breakout_buffer:
            return "BUY"
        if candle_close < range_low - breakout_buffer:
            return "SELL"
        return None

    latest_side = breakout_side(latest)
    close_is_outside = close > range_high or close < range_low
    if close > range_high:
        latest_side = "BUY"
    elif close < range_low:
        latest_side = "SELL"

    strong_body = body >= float(atr_1h)
    directional_candle = bool(
        (latest_side == "BUY" and close > open_price)
        or (latest_side == "SELL" and close < open_price)
    )
    small_breakout_wick = bool(
        (latest_side == "BUY" and upper_wick <= candle_range * 0.20)
        or (latest_side == "SELL" and lower_wick <= candle_range * 0.20)
    )
    supporting_checks = {
        "directional_breakout_candle": directional_candle,
        "strong_body_at_least_1_atr": bool(strong_body),
        "small_wick_on_breakout_side": bool(small_breakout_wick),
        "adx_rising_above_25": bool(adx_rising_above_25),
        "higher_timeframe_not_opposing": bool(higher_timeframe_not_opposing),
    }
    supporting_score = sum(bool(value) for value in supporting_checks.values())
    supporting_required = 3

    # Tick volume is not supplied by this Deriv candle normalisation path.
    # It is explicitly reported as unavailable rather than inferred.
    volume_confirmation = None

    recent_breakout_events = []
    active_breakout = None
    failed_breakout = None
    for candle in one_hour[-4:]:
        side = breakout_side(candle)
        candle_close = float(candle["close"])
        candle_outside = candle_close > range_high or candle_close < range_low

        if active_breakout and not candle_outside:
            # The first close back inside the range invalidates that attempt.
            failed_breakout = dict(active_breakout)
            active_breakout = None

        if side:
            active_breakout = {
                "direction": side,
                "epoch": int(candle["epoch"]),
                "close": round(candle_close, 5),
            }
            recent_breakout_events.append(dict(active_breakout))

    previous_breakout = (
        active_breakout
        if active_breakout and active_breakout["epoch"] != int(latest["epoch"])
        else None
    )

    status = "NO_BREAKOUT"
    breakout_direction = latest_side or (
        previous_breakout["direction"] if previous_breakout else
        failed_breakout["direction"] if failed_breakout else None
    )
    status_reason = "No completed 1H candle has decisively closed outside the 4H range."
    retest_confirmed = False
    breakout_attempt = bool(latest_side)

    # A close back inside within the observed three-bar follow-through window
    # records a failed breakout. A new close outside later starts a fresh attempt.
    if failed_breakout and not close_is_outside:
        status = "FAILED BREAKOUT"
        breakout_direction = failed_breakout["direction"]
        status_reason = "Price closed back inside the 4H range within the next three completed 1H candles."

    elif previous_breakout and close_is_outside:
        prior_direction = previous_breakout["direction"]
        prior_level = range_high if prior_direction == "BUY" else range_low
        retest_tolerance = max(float(atr_1h) * 0.25, breakout_buffer)
        tested_boundary = (
            low <= prior_level + retest_tolerance
            if prior_direction == "BUY"
            else high >= prior_level - retest_tolerance
        )
        held_outside = (
            close > prior_level + breakout_buffer
            if prior_direction == "BUY"
            else close < prior_level - breakout_buffer
        )
        directionally_rejected = (
            close > open_price
            and (close - low) / candle_range >= 0.65
            if prior_direction == "BUY"
            else close < open_price
            and (high - close) / candle_range >= 0.65
        )

        if tested_boundary and held_outside:
            breakout_direction = prior_direction
            retest_confirmed = bool(
                directionally_rejected and higher_timeframe_not_opposing
            )
            if retest_confirmed:
                status = "RETEST CONFIRMED"
                status_reason = "The 1H retest held the 4H boundary and closed with directional rejection."
            else:
                status = "BREAKOUT RETEST"
                status_reason = "The 1H candle retested the 4H boundary; continuation is not yet fully confirmed."
        elif (
            prior_direction == latest_side
            and (
                (prior_direction == "BUY" and close > float(one_hour[-2]["close"]))
                or (prior_direction == "SELL" and close < float(one_hour[-2]["close"]))
            )
            and higher_timeframe_not_opposing
            and adx_rising_above_25
        ):
            breakout_direction = prior_direction
            status = "BREAKOUT CONFIRMED"
            status_reason = "A second completed 1H candle accepted beyond the 4H boundary with follow-through."
        else:
            breakout_direction = prior_direction
            status = "BREAKOUT ATTEMPT"
            status_reason = "Price remains outside the range, but acceptance or retest confirmation is insufficient."

    elif latest_side:
        breakout_direction = latest_side
        if directional_candle and supporting_score >= supporting_required:
            status = "BREAKOUT CONFIRMED"
            status_reason = "The 1H close cleared the 4H range and passed at least three supporting confirmations."
        else:
            status = "BREAKOUT ATTEMPT"
            status_reason = "The 1H close moved beyond the 4H range but did not pass the confirmation score."

    elif close_is_outside:
        # A close outside but inside the decisive buffer is only an attempt.
        breakout_direction = "BUY" if close > range_high else "SELL"
        status = "BREAKOUT ATTEMPT"
        status_reason = "The 1H candle closed outside the range, but not far enough beyond the ATR buffer."

    return {
        "ready": True,
        "status": status,
        "reason": status_reason,
        "breakout_direction": breakout_direction,
        "signal_direction_matches": breakout_direction == direction if breakout_direction else None,
        "breakout_attempt": bool(breakout_attempt),
        "retest_confirmed": bool(retest_confirmed),
        "latest_1h_candle_epoch": int(latest["epoch"]),
        "latest_1h_close": round(close, 5),
        "breakout_buffer": round(breakout_buffer, 5),
        "atr_1h": round(float(atr_1h), 5),
        "candle_body": round(body, 5),
        "candle_body_atr": round(body / float(atr_1h), 3),
        "directional_breakout_candle": bool(directional_candle),
        "upper_wick_ratio": round(upper_wick / candle_range, 3),
        "lower_wick_ratio": round(lower_wick / candle_range, 3),
        "supporting_checks": supporting_checks,
        "supporting_score": supporting_score,
        "supporting_score_required": supporting_required,
        "supporting_score_available": len(supporting_checks),
        "volume_confirmation": volume_confirmation,
        "volume_note": "Tick volume is unavailable in the current Deriv OHLC candle payload and was not scored.",
        "adx_1h": round(adx_1h, 2) if adx_1h is not None else None,
        "previous_adx_1h": round(previous_adx_1h, 2) if previous_adx_1h is not None else None,
        "adx_rising": bool(adx_rising),
        "adx_crossed_25": bool(adx_crossed_25),
        "adx_expanded_from_below_20": bool(adx_expanded_from_below_20),
        "higher_timeframe_context": pre_breakout_context,
        "higher_timeframe_not_opposing": bool(higher_timeframe_not_opposing),
        "recent_breakout_events": recent_breakout_events,
        "failed_breakout_event": failed_breakout,
        **base_diagnostics,
    }


def _market_structure(candles: list[dict[str, Any]], direction: str, atr: float) -> dict[str, Any]:
    """Measure recent closed-candle structure without using the live candle."""
    if len(candles) < 25 or atr <= 0:
        return {"ready": False, "breakout": False, "retest": False, "swing_break": False}

    latest = candles[-1]
    previous_candle = candles[-2]
    prior = candles[-21:-1]
    prior_high = max(float(c["high"]) for c in prior)
    prior_low = min(float(c["low"]) for c in prior)
    close = float(latest["close"])
    tolerance = max(atr * 0.20, abs(close) * 0.0001)
    retest_reference = candles[-22:-2]
    reference_high = max(float(c["high"]) for c in retest_reference)
    reference_low = min(float(c["low"]) for c in retest_reference)

    if direction == "BUY":
        breakout = close > prior_high
        retest = (
            float(previous_candle["close"]) > reference_high
            and float(latest["low"]) <= reference_high + tolerance
            and close > reference_high
        )
        swing_break = breakout
        broken_level = prior_high
    else:
        breakout = close < prior_low
        retest = (
            float(previous_candle["close"]) < reference_low
            and float(latest["high"]) >= reference_low - tolerance
            and close < reference_low
        )
        swing_break = breakout
        broken_level = prior_low

    return {
        "ready": True,
        "breakout": bool(breakout),
        "retest": bool(retest),
        "swing_break": bool(swing_break),
        "prior_range_high": round(prior_high, 5),
        "prior_range_low": round(prior_low, 5),
        "broken_level": round(broken_level, 5),
    }


def _classify_market_and_setup(
    candles: list[dict[str, Any]],
    direction: str,
    atr: float,
    analysis: dict[str, Any],
    context: dict[str, Any],
    candles_by_timeframe: dict[str, list[dict[str, Any]]],
    as_of_epoch: int,
    sniper: bool,
    htf_points: int,
) -> dict[str, Any]:
    """Classify the market regime and the independent 4H-range/1H-breakout state."""
    closes = [float(c["close"]) for c in candles]
    recent = candles[-30:]
    ema9 = analysis.get("ema9")
    ema21 = analysis.get("ema21")
    latest = candles[-1]
    previous = candles[-2]
    close = closes[-1]

    structure = _market_structure(candles, direction, atr)
    breakout_assessment = _assess_range_breakout(
        candles_by_timeframe, direction, as_of_epoch
    )
    prior_trend = "NEUTRAL"
    if ema9 is not None and ema21 is not None:
        if ema9 > ema21:
            prior_trend = "BULLISH"
        elif ema9 < ema21:
            prior_trend = "BEARISH"

    ranges = [float(c["high"]) - float(c["low"]) for c in recent]
    average_range = sum(ranges[:-1]) / max(1, len(ranges) - 1)
    current_range = ranges[-1]
    volatility_ratio = current_range / max(average_range, 1e-9)

    # Measure price/EMA21 crossings against a rolling EMA, not one fixed
    # final EMA value. Repeated crossings plus poor directional efficiency
    # identify a genuinely choppy market rather than a clean sideways range.
    rolling_sides = []
    first_end = max(21, len(closes) - 19)
    for end_index in range(first_end, len(closes) + 1):
        rolling_ema21 = calculate_ema(closes[:end_index], 21)
        if rolling_ema21 is None:
            continue
        rolling_sides.append(
            1 if closes[end_index - 1] >= rolling_ema21 else -1
        )

    ema_crosses = sum(
        1 for left, right in zip(rolling_sides, rolling_sides[1:])
        if left != right
    )

    efficiency_window = closes[-20:] if len(closes) >= 20 else closes
    total_path = sum(
        abs(efficiency_window[i] - efficiency_window[i - 1])
        for i in range(1, len(efficiency_window))
    )
    directional_efficiency = (
        abs(efficiency_window[-1] - efficiency_window[0]) / total_path
        if total_path > 0 else 0.0
    )

    ema_spread = abs(float(ema9 or close) - float(ema21 or close))

    # A compact range is distinct from a choppy market: a range can be
    # orderly and respect boundaries; chop repeatedly whipsaws around EMA21.
    range_window = candles[-21:-1]
    range_high = max(float(c["high"]) for c in range_window)
    range_low = min(float(c["low"]) for c in range_window)
    range_width = range_high - range_low
    range_width_atr = range_width / max(float(atr), 1e-9)
    compact_range = 1.5 <= range_width_atr <= 10.0

    if ema_crosses >= 5 and directional_efficiency <= 0.30:
        market_condition = "CHOPPY"
    elif volatility_ratio >= 2.0:
        market_condition = "HIGH VOLATILITY"
    elif volatility_ratio <= 0.45:
        market_condition = "LOW VOLATILITY"
    elif ema_spread <= 0.30 * atr and compact_range:
        market_condition = "RANGING"
    elif (
        direction == "BUY" and prior_trend == "BULLISH"
        or direction == "SELL" and prior_trend == "BEARISH"
    ):
        market_condition = "TRENDING"
    else:
        market_condition = "RANGING" if compact_range else "TRENDING"

    directional_context = [
        context.get(tf, {}).get("trend")
        for tf in ("1D", "4H", "1H")
        if context.get(tf, {}).get("ready")
    ]
    opposite_htf = any(
        trend == ("BEARISH" if direction == "BUY" else "BULLISH")
        for trend in directional_context
    )
    matching_htf = sum(
        trend == ("BULLISH" if direction == "BUY" else "BEARISH")
        for trend in directional_context
    )

    pattern = _candle_pattern(latest, previous)
    reversal_candle = (
        pattern["bullish"] if direction == "BUY" else pattern["bearish"]
    )
    level_rejection = any(
        item.get("confluences", {}).get(
            "bullish_level_rejection" if direction == "BUY" else "bearish_level_rejection",
            False,
        )
        for item in context.values()
        if item.get("confluences", {}).get("ready")
    )

    # RANGE REVERSAL requires an established sideways range, repeated tests
    # of the relevant boundary, a rejection wick/pattern, and a close back
    # inside the prior range. A CHOPPY regime is never relabelled as a
    # range reversal merely because the 15M scanner found a direction.
    boundary_tolerance = max(float(atr) * 0.25, abs(close) * 0.0001)
    support_touches = sum(
        1 for candle in range_window
        if float(candle["low"]) <= range_low + boundary_tolerance
    )
    resistance_touches = sum(
        1 for candle in range_window
        if float(candle["high"]) >= range_high - boundary_tolerance
    )

    buy_range_reversal = (
        direction == "BUY"
        and market_condition == "RANGING"
        and compact_range
        and support_touches >= 2
        and float(latest["low"]) <= range_low + boundary_tolerance
        and close > range_low + 0.05 * atr
        and close > float(latest["open"])
        and pattern["bullish"]
    )
    sell_range_reversal = (
        direction == "SELL"
        and market_condition == "RANGING"
        and compact_range
        and resistance_touches >= 2
        and float(latest["high"]) >= range_high - boundary_tolerance
        and close < range_high - 0.05 * atr
        and close < float(latest["open"])
        and pattern["bearish"]
    )
    range_reversal_confirmed = buy_range_reversal or sell_range_reversal
    range_reversal_boundary = (
        "SUPPORT" if buy_range_reversal else
        "RESISTANCE" if sell_range_reversal else None
    )

    breakout_status = breakout_assessment.get("status")
    breakout_direction = breakout_assessment.get("breakout_direction")
    if (
        breakout_status == "FAILED BREAKOUT"
        and breakout_direction == direction
    ):
        setup_type = "FAILED BREAKOUT"
    elif (
        breakout_status == "RETEST CONFIRMED"
        and breakout_direction == direction
    ):
        setup_type = "RETEST CONFIRMED"
        market_condition = "BREAKOUT CONFIRMED"
    elif (
        breakout_status == "BREAKOUT CONFIRMED"
        and breakout_direction == direction
    ):
        setup_type = "BREAKOUT CONFIRMED"
        market_condition = "BREAKOUT CONFIRMED"
    elif (
        breakout_status == "BREAKOUT RETEST"
        and breakout_direction == direction
    ):
        setup_type = "BREAKOUT RETEST"
    elif (
        breakout_status == "BREAKOUT ATTEMPT"
        and breakout_direction == direction
    ):
        setup_type = "BREAKOUT ATTEMPT"
    elif opposite_htf and structure.get("swing_break"):
        setup_type = "CONFIRMED REVERSAL"
    elif opposite_htf and (reversal_candle or level_rejection):
        setup_type = "EARLY REVERSAL"
    elif market_condition == "CHOPPY":
        # Keep the market-state label explicit; ordinary chop is not a
        # support/resistance reversal setup.
        setup_type = "CHOPPY"
    elif range_reversal_confirmed:
        setup_type = "RANGE REVERSAL"
    elif prior_trend == ("BULLISH" if direction == "BUY" else "BEARISH") and matching_htf:
        setup_type = "TREND CONTINUATION"
    elif opposite_htf:
        setup_type = "COUNTERTREND"
    else:
        setup_type = "MOMENTUM"

    primary_score = max(
        int(analysis.get("buy_score") or 0),
        int(analysis.get("sell_score") or 0),
    )
    if sniper:
        quality_tier = "SNIPER"
    elif primary_score >= 5 and matching_htf >= 1 and not opposite_htf:
        quality_tier = "STANDARD"
    else:
        quality_tier = "QUICK SCALP"

    return {
        "setup_type": setup_type,
        "quality_tier": quality_tier,
        "market_condition": market_condition,
        "market_structure": structure,
        "breakout_assessment": breakout_assessment,
        "range_reversal": {
            "confirmed": range_reversal_confirmed,
            "boundary": range_reversal_boundary,
            "range_high": round(range_high, 5),
            "range_low": round(range_low, 5),
            "range_width_atr": round(range_width_atr, 3),
            "support_touches": support_touches,
            "resistance_touches": resistance_touches,
            "reversal_candle": bool(reversal_candle),
        },
        "chop_diagnostics": {
            "ema21_crosses": ema_crosses,
            "directional_efficiency": round(directional_efficiency, 3),
        },
        "volatility_ratio": round(volatility_ratio, 3),
        "higher_timeframe_alignment": {
            "matching": matching_htf,
            "opposing": opposite_htf,
        },
    }

def analyse_precision_opportunity(
    candles_by_timeframe: dict[str, list[dict[str, Any]]],
    as_of_epoch: int,
) -> dict[str, Any]:
    """
    RevAI multi-timeframe confluence engine.
    15M independently qualifies the trade. 1D/4H/1H add context and
    reversal evidence; 5M is optional entry refinement and never blocks 15M.
    """
    if "15M" not in candles_by_timeframe:
        return _wait("15M", "Missing 15M candle data.", as_of_epoch=as_of_epoch)

    context = {}
    for tf in ("1D", "4H", "1H"):
        if tf in candles_by_timeframe:
            trend = _trend_context(candles_by_timeframe[tf], tf, as_of_epoch)
            confluence = _timeframe_confluences(candles_by_timeframe[tf], tf, as_of_epoch)
            context[tf] = {**trend, "confluences": confluence}
        else:
            context[tf] = {
                "timeframe": tf, "trend": "UNAVAILABLE", "ready": False,
                "reason": f"{tf} candle data was not supplied.",
                "confluences": {"timeframe": tf, "ready": False},
            }

    # Do not make higher-timeframe trend agreement a hard gate. The 15M
    # scanner owns direction; higher timeframes strengthen or weaken confidence.
    setup_15m = _detect_15m_setup(candles_by_timeframe["15M"], as_of_epoch)
    if not setup_15m.get("qualified"):
        return _wait(
            "15M", setup_15m.get("reason", "15M setup is not qualified."),
            context=context, setup_15m=setup_15m,
            analysis=setup_15m.get("analysis"),
            buy_score=setup_15m.get("buy_score"),
            sell_score=setup_15m.get("sell_score"),
            as_of_epoch=as_of_epoch,
        )

    direction = setup_15m.get("signal")
    if direction not in ("BUY", "SELL"):
        return _wait("15M", "15M scanner did not return a valid direction.",
                     context=context, setup_15m=setup_15m, as_of_epoch=as_of_epoch)

    # Add 15M and 5M candle/band evidence. 5M remains optional.
    confluences = {}
    for tf in ("15M", "5M"):
        candles = candles_by_timeframe.get(tf)
        if candles:
            confluences[tf] = _timeframe_confluences(candles, tf, as_of_epoch)
        else:
            confluences[tf] = {"timeframe": tf, "ready": False, "reason": "Data unavailable."}

    # Score only higher-timeframe evidence for SNIPER. One timeframe can
    # contribute a maximum of 2 points: reversal at a horizontal level and
    # matching Bollinger rejection. This avoids double-counting a wick touch.
    htf_points = 0
    htf_evidence = []
    for tf in ("1D", "4H", "1H"):
        item = context[tf].get("confluences", {})
        if not item.get("ready"):
            continue
        if direction == "BUY":
            level_rejection = item.get("bullish_level_rejection", False)
            band_rejection = item.get("bullish_band_rejection", False)
            reversal = item.get("bullish_reversal_candle", False)
        else:
            level_rejection = item.get("bearish_level_rejection", False)
            band_rejection = item.get("bearish_band_rejection", False)
            reversal = item.get("bearish_reversal_candle", False)
        points = int(bool(reversal and level_rejection)) + int(bool(reversal and band_rejection))
        if points:
            htf_points += points
            htf_evidence.append({
                "timeframe": tf, "points": points,
                "reversal_candle": True,
                "horizontal_level_rejection": bool(level_rejection),
                "bollinger_rejection": bool(band_rejection),
            })

    # SNIPER requires multi-timeframe evidence: at least 2 HTF confluence
    # points, including evidence from Daily or H4. It is a label, not a gate.
    major_htf_present = any(x["timeframe"] in ("1D", "4H") for x in htf_evidence)
    sniper = htf_points >= 2 and major_htf_present
    classification = "SNIPER" if sniper else "STANDARD"

    five_minute = confluences["5M"]
    confirmation_5m = (
        _confirm_5m(candles_by_timeframe["5M"], as_of_epoch, direction)
        if candles_by_timeframe.get("5M") else
        {"qualified": False, "reason": "5M data unavailable; using 15M entry reference."}
    )

    # Use 5M close only when its own confirmation qualifies. Otherwise use
    # the closed 15M close; a 5M disagreement/absence cannot cancel the signal.
    five_closed = _closed_candles(candles_by_timeframe.get("5M", []), "5M", as_of_epoch)
    fifteen_closed = _closed_candles(candles_by_timeframe["15M"], "15M", as_of_epoch)
    use_5m = bool(confirmation_5m.get("qualified") and five_closed)
    entry_candles = five_closed if use_5m else fifteen_closed
    entry_timeframe = "5M" if use_5m else "15M"
    if len(entry_candles) < 30:
        # Risk can still be calculated from the available 15M history.
        entry_candles = fifteen_closed
        entry_timeframe = "15M"
        use_5m = False
    if len(entry_candles) < 22:
        return _wait(
            "15M", "Insufficient closed candles to calculate a safe structural stop.",
            direction_bias=direction, context=context, setup_15m=setup_15m,
            confirmation_5m=confirmation_5m, confluences=confluences,
            as_of_epoch=as_of_epoch,
        )

    entry = float(entry_candles[-1]["close"])
    atr = calculate_atr(entry_candles)
    if not atr or atr <= 0:
        return _wait("15M", "ATR unavailable for risk calculation.",
                     direction_bias=direction, context=context, setup_15m=setup_15m,
                     confirmation_5m=confirmation_5m, as_of_epoch=as_of_epoch)

    recent = entry_candles[-6:]
    if direction == "BUY":
        stop_loss = min(float(c["low"]) for c in recent) - 0.1 * atr
        risk = entry - stop_loss
        targets = [entry + risk, entry + 1.5 * risk, entry + 2.0 * risk]
    else:
        stop_loss = max(float(c["high"]) for c in recent) + 0.1 * atr
        risk = stop_loss - entry
        targets = [entry - risk, entry - 1.5 * risk, entry - 2.0 * risk]

    if risk <= 0 or risk > 2.5 * atr:
        return _wait(
            "15M", "Structural stop is invalid or wider than 2.5 ATR.",
            direction_bias=direction, entry=round(entry, 2),
            stop_loss=round(stop_loss, 2), risk=round(risk, 4),
            atr=round(float(atr), 4), context=context, setup_15m=setup_15m,
            confirmation_5m=confirmation_5m, confluences=confluences,
            as_of_epoch=as_of_epoch,
        )

    analysis = setup_15m.get("analysis") or {}
    classification_details = _classify_market_and_setup(
        fifteen_closed, direction, float(atr), analysis, context,
        candles_by_timeframe, as_of_epoch, sniper, htf_points
    )
    primary_score = max(
        int(setup_15m.get("buy_score") or 0),
        int(setup_15m.get("sell_score") or 0),
    )
    matching_htf = classification_details["higher_timeframe_alignment"]["matching"]
    if sniper:
        classification_details["quality_tier"] = "SNIPER"
    elif primary_score >= 5 and matching_htf >= 1 and not classification_details["higher_timeframe_alignment"]["opposing"]:
        classification_details["quality_tier"] = "STANDARD"
    else:
        classification_details["quality_tier"] = "QUICK SCALP"
    return {
        "timeframe": "15M",
        "strategy": "RevAI Multi-Timeframe Confluence Engine",
        "signal": direction,
        "qualified": True,
        "classification": classification,
        "quality_tier": classification_details["quality_tier"],
        "setup_type": classification_details["setup_type"],
        "market_condition": classification_details["market_condition"],
        "classification_details": classification_details,
        "sniper": sniper,
        "sniper_score": htf_points,
        "sniper_evidence": htf_evidence,
        "reason": (
            "15M setup qualified; higher-timeframe confluences support SNIPER classification."
            if sniper else
            "15M setup qualified. Higher-timeframe evidence does not meet the SNIPER threshold."
        ),
        "as_of_epoch": as_of_epoch,
        "entry": round(entry, 2),
        "entry_timeframe": entry_timeframe,
        "stop_loss": round(stop_loss, 2),
        "tp1": round(targets[0], 2),
        "tp2": round(targets[1], 2),
        "tp3": round(targets[2], 2),
        "risk_price": round(risk, 4),
        "reward_risk_tp2": 1.5,
        "buy_score": setup_15m.get("buy_score", 0),
        "sell_score": setup_15m.get("sell_score", 0),
        "analysis": analysis,
        "context": context,
        "confluences": confluences,
        "setup_15m": setup_15m,
        "confirmation_5m": confirmation_5m,
        "execution_timeframe": entry_timeframe,
        "signal_timeframe": "15M",
    }


def analyse_v2_dashboard(
    candles_by_timeframe: dict[str, list[dict[str, Any]]],
    as_of_epoch: int,
) -> dict[str, Any]:
    precision = analyse_precision_opportunity(candles_by_timeframe, as_of_epoch)
    return {
        "symbol": "frxXAUUSD",
        "strategy": "RevAI Multi-Timeframe Confluence Engine",
        "as_of_epoch": as_of_epoch,
        "signal": precision,
        "signals": {"15M": precision},
        "context": precision.get("context", {}),
        "note": (
            "15M independently generates signals. 1D/4H/1H add reversal "
            "context; 5M optionally refines entry. SNIPER labels high-confluence setups."
        ),
    }
