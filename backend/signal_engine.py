
from __future__ import annotations

import time
from typing import Any, Optional


TIMEFRAME_SECONDS = {
    "1D": 86400,
    "4H": 14400,
    "1H": 3600,
    "15M": 900,
    "5M": 300,
}


def calculate_ema(
    values: list[float],
    period: int
) -> Optional[float]:

    if len(values) < period:
        return None

    ema = sum(values[:period]) / period
    multiplier = 2 / (period + 1)

    for price in values[period:]:
        ema = (price * multiplier) + (ema * (1 - multiplier))

    return ema


def calculate_rsi(
    values: list[float],
    period: int = 14
) -> Optional[float]:

    if len(values) < period + 1:
        return None

    changes = [
        values[i] - values[i - 1]
        for i in range(len(values) - period, len(values))
    ]

    gains = [change for change in changes if change > 0]
    losses = [-change for change in changes if change < 0]

    average_gain = sum(gains) / period
    average_loss = sum(losses) / period

    if average_loss == 0:
        return 50.0 if average_gain == 0 else 100.0

    relative_strength = average_gain / average_loss

    return 100 - (100 / (1 + relative_strength))


def calculate_atr(
    candles: list[dict[str, Any]],
    period: int = 14
) -> Optional[float]:

    if len(candles) < period + 1:
        return None

    true_ranges = []

    for index in range(1, len(candles)):
        current = candles[index]
        previous = candles[index - 1]

        true_range = max(
            current["high"] - current["low"],
            abs(current["high"] - previous["close"]),
            abs(current["low"] - previous["close"]),
        )

        true_ranges.append(true_range)

    return sum(true_ranges[-period:]) / period


def analyse_timeframe(
    candles: list[dict[str, Any]],
    timeframe: str,
    as_of_epoch: Optional[int] = None
) -> dict[str, Any]:

    if timeframe not in TIMEFRAME_SECONDS:
        return {
            "timeframe": timeframe,
            "signal": "WAIT",
            "reason": "Unsupported timeframe.",
        }

    candles = sorted(
        candles,
        key=lambda candle: candle["epoch"]
    )

    if len(candles) < 30:
        return {
            "timeframe": timeframe,
            "signal": "WAIT",
            "reason": "Insufficient candle history. At least 30 candles required.",
            "candles_received": len(candles),
        }

    # Live analysis uses current time.
    # Historical backtesting supplies its own simulated timestamp.
    if as_of_epoch is None:
        as_of_epoch = int(time.time())

    duration = TIMEFRAME_SECONDS[timeframe]

    # Only candles that have fully closed at the analysis timestamp.
    closed_candles = [
        candle for candle in candles
        if candle["epoch"] + duration <= as_of_epoch
    ]

    if len(closed_candles) < 30:
        return {
            "timeframe": timeframe,
            "signal": "WAIT",
            "reason": "Insufficient closed candles.",
            "candles_received": len(candles),
            "closed_candles": len(closed_candles),
        }

    closes = [
        float(candle["close"])
        for candle in closed_candles
    ]

    ema9 = calculate_ema(closes, 9)
    ema21 = calculate_ema(closes, 21)
    rsi = calculate_rsi(closes)
    atr = calculate_atr(closed_candles)

    if None in (ema9, ema21, rsi, atr):
        return {
            "timeframe": timeframe,
            "signal": "WAIT",
            "reason": "Indicator calculation unavailable.",
        }

    latest = closed_candles[-1]
    previous = closed_candles[-2]

    bullish_momentum = closes[-1] > closes[-6]
    bearish_momentum = closes[-1] < closes[-6]

    bullish_confirmation = (
        latest["close"] > latest["open"]
        and latest["close"] > previous["high"]
    )

    bearish_confirmation = (
        latest["close"] < latest["open"]
        and latest["close"] < previous["low"]
    )

    buy_checks = [
        ema9 > ema21,
        latest["close"] > ema9,
        bullish_momentum,
        48 <= rsi <= 72,
        bullish_confirmation,
    ]

    sell_checks = [
        ema9 < ema21,
        latest["close"] < ema9,
        bearish_momentum,
        28 <= rsi <= 52,
        bearish_confirmation,
    ]

    check_names = [
        "EMA 9 versus EMA 21",
        "Price versus EMA 9",
        "Five-candle momentum",
        "RSI range",
        "Candle breakout confirmation",
    ]

    diagnostics = {
        "ema9": round(ema9, 2),
        "ema21": round(ema21, 2),
        "latest_close": round(float(latest["close"]), 2),
        "previous_high": round(float(previous["high"]), 2),
        "previous_low": round(float(previous["low"]), 2),
        "rsi": round(rsi, 2),
        "atr": round(atr, 3),
        "bullish_momentum": bullish_momentum,
        "bearish_momentum": bearish_momentum,
        "bullish_confirmation": bullish_confirmation,
        "bearish_confirmation": bearish_confirmation,
        "buy_checks": {
            name: bool(passed)
            for name, passed in zip(check_names, buy_checks)
        },
        "sell_checks": {
            name: bool(passed)
            for name, passed in zip(check_names, sell_checks)
        },
        "buy_reasons": [
            name for name, passed in zip(check_names, buy_checks) if passed
        ],
        "buy_failed_checks": [
            name for name, passed in zip(check_names, buy_checks) if not passed
        ],
        "sell_reasons": [
            name for name, passed in zip(check_names, sell_checks) if passed
        ],
        "sell_failed_checks": [
            name for name, passed in zip(check_names, sell_checks) if not passed
        ],
    }

    buy_score = sum(buy_checks)
    sell_score = sum(sell_checks)

    if buy_score >= 4 and buy_score > sell_score:
        direction = "BUY"

    elif sell_score >= 4 and sell_score > buy_score:
        direction = "SELL"

    else:
        return {
            "timeframe": timeframe,
            "signal": "WAIT",
            "reason": "No qualified setup.",
            "analysis": diagnostics,
            "buy_score": buy_score,
            "sell_score": sell_score,
            "rsi": round(rsi, 2),
            "atr": round(atr, 3),
            "candles_received": len(candles),
            "closed_candles": len(closed_candles),
        }

    # Stop loss based on the latest six closed candles.
    recent = closed_candles[-6:]

    if direction == "BUY":
        stop_loss = min(
            candle["low"] for candle in recent
        ) - (0.1 * atr)

        entry = latest["close"]
        risk = entry - stop_loss

    else:
        stop_loss = max(
            candle["high"] for candle in recent
        ) + (0.1 * atr)

        entry = latest["close"]
        risk = stop_loss - entry

    if risk <= 0 or risk > 2.5 * atr:
        return {
            "timeframe": timeframe,
            "signal": "WAIT",
            "reason": "Stop distance is invalid or too wide.",
            "analysis": diagnostics,
        }

    if direction == "BUY":
        targets = [
            entry + risk,
            entry + (1.5 * risk),
            entry + (2 * risk),
        ]

    else:
        targets = [
            entry - risk,
            entry - (1.5 * risk),
            entry - (2 * risk),
        ]

    return {
        "timeframe": timeframe,
        "signal": direction,
        "reason": "Qualified setup.",
        "analysis": diagnostics,
        "entry": round(entry, 2),
        "stop_loss": round(stop_loss, 2),
        "tp1": round(targets[0], 2),
        "tp2": round(targets[1], 2),
        "tp3": round(targets[2], 2),
        "buy_score": buy_score,
        "sell_score": sell_score,
        "rsi": round(rsi, 2),
        "atr": round(atr, 3),
        "candles_received": len(candles),
        "closed_candles": len(closed_candles),
    }
