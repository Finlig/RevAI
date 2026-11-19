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
    sniper: bool,
    htf_points: int,
) -> dict[str, Any]:
    """Return distinct setup type, quality tier and market regime labels."""
    closes = [float(c["close"]) for c in candles]
    recent = candles[-30:]
    ema9 = analysis.get("ema9")
    ema21 = analysis.get("ema21")
    latest = candles[-1]
    previous = candles[-2]
    close = closes[-1]

    structure = _market_structure(candles, direction, atr)
    prior_trend = "NEUTRAL"
    if ema9 is not None and ema21 is not None:
        if ema9 > ema21:
            prior_trend = "BULLISH"
        elif ema9 < ema21:
            prior_trend = "BEARISH"

    # Volatility is measured against recent candle ranges to adapt to Gold's
    # changing price scale rather than relying on a fixed dollar threshold.
    ranges = [float(c["high"]) - float(c["low"]) for c in recent]
    average_range = sum(ranges[:-1]) / max(1, len(ranges) - 1)
    current_range = ranges[-1]
    volatility_ratio = current_range / max(average_range, 1e-9)

    # Count EMA relationship flips over the recent window as a chop proxy.
    crosses = 0
    for i in range(2, min(20, len(closes))):
        left = closes[-i] - (ema21 or closes[-i])
        right = closes[-i - 1] - (ema21 or closes[-i - 1])
        if left == 0 or right == 0 or (left > 0) != (right > 0):
            crosses += 1

    ema_spread = abs(float(ema9 or close) - float(ema21 or close))
    if volatility_ratio >= 2.0:
        market_condition = "HIGH VOLATILITY"
    elif volatility_ratio <= 0.45:
        market_condition = "LOW VOLATILITY"
    elif crosses >= 7:
        market_condition = "CHOPPY"
    elif ema_spread <= 0.30 * atr:
        market_condition = "RANGING"
    elif (
        direction == "BUY" and prior_trend == "BULLISH"
        or direction == "SELL" and prior_trend == "BEARISH"
    ):
        market_condition = "TRENDING"
    else:
        market_condition = "RANGING"

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

    reversal_candle = (
        _candle_pattern(latest, previous).get("bullish")
        if direction == "BUY"
        else _candle_pattern(latest, previous).get("bearish")
    )
    level_rejection = any(
        (
            item.get("confluences", {}).get(
                "bullish_level_rejection" if direction == "BUY" else "bearish_level_rejection",
                False,
            )
        )
        for item in context.values()
        if item.get("confluences", {}).get("ready")
    )

    if opposite_htf and structure.get("swing_break"):
        setup_type = "CONFIRMED REVERSAL"
    elif opposite_htf and (reversal_candle or level_rejection):
        # HTF disagreement plus a rejection is an early warning only.
        setup_type = "EARLY REVERSAL"
    elif structure.get("retest"):
        setup_type = "BREAKOUT RETEST"
    elif structure.get("breakout"):
        setup_type = "BREAKOUT"
        market_condition = "BREAKOUT CONFIRMED"
    elif prior_trend == ("BULLISH" if direction == "BUY" else "BEARISH") and matching_htf:
        setup_type = "TREND CONTINUATION"
    elif opposite_htf:
        setup_type = "COUNTERTREND"
    elif market_condition in ("RANGING", "CHOPPY"):
        setup_type = "RANGE REVERSAL"
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
        fifteen_closed, direction, float(atr), analysis, context, sniper, htf_points
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
