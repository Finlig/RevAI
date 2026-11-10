from __future__ import annotations

from collections import Counter
from typing import Any, Optional

from signal_engine import TIMEFRAME_SECONDS
from signal_engine_v2 import analyse_precision_opportunity


REQUIRED_TIMEFRAMES = ("4H", "1H", "15M", "5M")
ALL_TIMEFRAMES = ("1D", "4H", "1H", "15M", "5M")

# V2 enters on the first 5M candle after the signal candle has closed.
# A 30-candle holding limit is therefore 150 minutes on the execution chart.
MAX_HOLDING_BARS = 30
MIN_5M_HISTORY = 50

# Reject recent short/intraday data gaps in the entry/setup charts.
# Longer gaps are retained and counted, but stale timeframe data is still rejected.
SHORT_GAP_LIMIT_SECONDS = 6 * 60 * 60


def _normalise_candles(
    candles: list[dict[str, Any]],
    timeframe: str,
) -> list[dict[str, Any]]:
    """Sort, de-duplicate and retain structurally valid OHLC candles."""
    if timeframe not in TIMEFRAME_SECONDS:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    duration = TIMEFRAME_SECONDS[timeframe]
    unique: dict[int, dict[str, Any]] = {}

    import math

    for candle in candles:
        try:
            epoch = int(candle["epoch"])
            open_price = float(candle["open"])
            high = float(candle["high"])
            low = float(candle["low"])
            close = float(candle["close"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue

        prices = (open_price, high, low, close)
        if not all(math.isfinite(price) for price in prices):
            continue
        if high < low or high < max(open_price, close) or low > min(open_price, close):
            continue
        if epoch % duration != 0:
            continue

        unique[epoch] = {
            "epoch": epoch,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
        }

    return [unique[epoch] for epoch in sorted(unique)]


def _count_gaps(candles: list[dict[str, Any]], duration: int) -> int:
    return sum(
        1
        for previous, current in zip(candles, candles[1:])
        if current["epoch"] - previous["epoch"] != duration
    )


def _recent_has_short_gap(
    candles: list[dict[str, Any]],
    duration: int,
    lookback: int,
) -> bool:
    """Reject unexpected short gaps; do not label long closures as ordinary bars."""
    recent = candles[-(lookback + 1):]
    for previous, current in zip(recent, recent[1:]):
        difference = current["epoch"] - previous["epoch"]
        if duration < difference < SHORT_GAP_LIMIT_SECONDS:
            return True
    return False


def _closed_history(
    candles_by_timeframe: dict[str, list[dict[str, Any]]],
    as_of_epoch: int,
) -> dict[str, list[dict[str, Any]]]:
    """Only pass candles whose full close time is at or before the signal time."""
    result: dict[str, list[dict[str, Any]]] = {}
    for timeframe in ALL_TIMEFRAMES:
        duration = TIMEFRAME_SECONDS[timeframe]
        source = candles_by_timeframe.get(timeframe, [])
        result[timeframe] = [
            candle
            for candle in source
            if candle["epoch"] + duration <= as_of_epoch
        ]
    return result


def _data_ready(
    history: dict[str, list[dict[str, Any]]],
    as_of_epoch: int,
) -> tuple[bool, Optional[str]]:
    minimums = {"4H": 50, "1H": 50, "15M": 30, "5M": 30}

    for timeframe in REQUIRED_TIMEFRAMES:
        candles = history.get(timeframe, [])
        if len(candles) < minimums[timeframe]:
            return False, f"INSUFFICIENT_{timeframe}_HISTORY"

        duration = TIMEFRAME_SECONDS[timeframe]
        latest_close = candles[-1]["epoch"] + duration
        # Prevent a stale higher-timeframe series from authorising a new entry.
        if as_of_epoch - latest_close > 2 * duration:
            return False, f"STALE_{timeframe}_DATA"

    # Short unexpected gaps in the setup and execution windows make the
    # recent price path uncertain. Long closures remain visible in metrics.
    if _recent_has_short_gap(history["15M"], TIMEFRAME_SECONDS["15M"], 30):
        return False, "RECENT_15M_DATA_GAP"
    if _recent_has_short_gap(history["5M"], TIMEFRAME_SECONDS["5M"], 30):
        return False, "RECENT_5M_DATA_GAP"

    return True, None


def _make_trade(
    signal: dict[str, Any],
    entry_candle: dict[str, Any],
    entry_epoch: int,
) -> dict[str, Any] | None:
    direction = signal.get("signal")
    entry = float(entry_candle["open"])
    stop = float(signal["stop_loss"])

    if direction == "BUY":
        risk = entry - stop
        if risk <= 0:
            return None
        targets = (entry + risk, entry + 1.5 * risk, entry + 2.0 * risk)
    elif direction == "SELL":
        risk = stop - entry
        if risk <= 0:
            return None
        targets = (entry - risk, entry - 1.5 * risk, entry - 2.0 * risk)
    else:
        return None

    return {
        "timeframe": "PRECISION",
        "direction": direction,
        "signal_entry_reference": round(float(signal["entry"]), 2),
        "entry": round(entry, 2),
        "stop_loss": round(stop, 2),
        "tp1": round(targets[0], 2),
        "tp2": round(targets[1], 2),
        "tp3": round(targets[2], 2),
        "risk_price": round(risk, 4),
        "entry_epoch": entry_epoch,
        "signal_epoch": int(signal["as_of_epoch"]),
    }


def _finish_trade(
    trade: dict[str, Any],
    exit_price: float,
    exit_epoch: int,
    exit_reason: str,
    highest_target: int,
) -> dict[str, Any]:
    if trade["direction"] == "BUY":
        profit = exit_price - trade["entry"]
    else:
        profit = trade["entry"] - exit_price

    risk = trade["risk_price"]
    completed = dict(trade)
    completed.update(
        {
            "exit_price": round(float(exit_price), 2),
            "exit_epoch": int(exit_epoch),
            "exit_reason": exit_reason,
            "highest_target": highest_target,
            "r_multiple": round(profit / risk, 4),
        }
    )
    return completed


def _simulate_trade(
    trade: dict[str, Any],
    candles_5m: list[dict[str, Any]],
    entry_index: int,
) -> tuple[dict[str, Any], int]:
    """Simulate one trade from its next-candle-open entry, conservatively."""
    direction = trade["direction"]
    stop = trade["stop_loss"]
    tp1, tp2, tp3 = trade["tp1"], trade["tp2"], trade["tp3"]
    duration = TIMEFRAME_SECONDS["5M"]
    entry_epoch = trade["entry_epoch"]
    expiry_epoch = entry_epoch + MAX_HOLDING_BARS * duration
    highest_target = 0
    last_eligible_index = entry_index - 1

    for index in range(entry_index, len(candles_5m)):
        candle = candles_5m[index]
        candle_epoch = candle["epoch"]

        if candle_epoch >= expiry_epoch:
            break

        if index > 0:
            previous = candles_5m[index - 1]
            if candle_epoch - previous["epoch"] != duration:
                return (
                    _finish_trade(
                        trade, candle["open"], candle_epoch,
                        "DATA_GAP_EXIT", highest_target
                    ),
                    index,
                )

        last_eligible_index = index
        open_price = candle["open"]
        high = candle["high"]
        low = candle["low"]

        if direction == "BUY":
            if open_price <= stop:
                return _finish_trade(
                    trade, open_price, candle_epoch, "STOP_LOSS_GAP", highest_target
                ), index
            if open_price >= tp3:
                return _finish_trade(
                    trade, open_price, candle_epoch, "TP3_GAP", 3
                ), index
            # If stop and a target are both touched in one OHLC candle,
            # assume the stop happened first.
            if low <= stop:
                return _finish_trade(
                    trade, stop, candle_epoch + duration, "STOP_LOSS", highest_target
                ), index
            if high >= tp1:
                highest_target = max(highest_target, 1)
            if high >= tp2:
                highest_target = max(highest_target, 2)
            if high >= tp3:
                return _finish_trade(
                    trade, tp3, candle_epoch + duration, "TP3", 3
                ), index
        else:
            if open_price >= stop:
                return _finish_trade(
                    trade, open_price, candle_epoch, "STOP_LOSS_GAP", highest_target
                ), index
            if open_price <= tp3:
                return _finish_trade(
                    trade, open_price, candle_epoch, "TP3_GAP", 3
                ), index
            if high >= stop:
                return _finish_trade(
                    trade, stop, candle_epoch + duration, "STOP_LOSS", highest_target
                ), index
            if low <= tp1:
                highest_target = max(highest_target, 1)
            if low <= tp2:
                highest_target = max(highest_target, 2)
            if low <= tp3:
                return _finish_trade(
                    trade, tp3, candle_epoch + duration, "TP3", 3
                ), index

    if last_eligible_index < entry_index:
        # No eligible future bar: do not fabricate an exit price.
        return _finish_trade(
            trade, trade["entry"], entry_epoch, "NO_FUTURE_CANDLE", 0
        ), max(entry_index - 1, 0)

    last = candles_5m[last_eligible_index]
    reason = "TIMEOUT" if highest_target == 0 else f"TIMEOUT_AFTER_TP{highest_target}"
    return _finish_trade(
        trade, last["close"], last["epoch"] + duration, reason, highest_target
    ), last_eligible_index


def calculate_v2_metrics(
    candles_5m: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    *,
    data_gaps: dict[str, int],
    skipped_reasons: Counter,
    rejected_entries: int,
) -> dict[str, Any]:
    total = len(trades)
    wins = sum(t["r_multiple"] > 0 for t in trades)
    losses = sum(t["r_multiple"] < 0 for t in trades)
    breakeven = total - wins - losses
    gross_profit = sum(t["r_multiple"] for t in trades if t["r_multiple"] > 0)
    gross_loss = abs(sum(t["r_multiple"] for t in trades if t["r_multiple"] < 0))
    equity = peak = max_drawdown = 0.0

    for trade in trades:
        equity += trade["r_multiple"]
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)

    if total == 0:
        status = "NO_TRADES"
    else:
        status = "COMPLETED"

    return {
        "strategy": "RevAI Gold Precision Engine V2",
        "execution_timeframe": "5M",
        "status": status,
        "candles_tested": len(candles_5m),
        "data_gaps_detected": data_gaps,
        "skipped_setups_by_reason": dict(skipped_reasons),
        "rejected_entries": rejected_entries,
        "maximum_holding_bars": MAX_HOLDING_BARS,
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "breakeven_trades": breakeven,
        "win_rate_percent": round(wins / total * 100, 2) if total else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss else (
            None if gross_profit == 0 else "INFINITE"
        ),
        "gross_profit_r": round(gross_profit, 3),
        "gross_loss_r": round(gross_loss, 3),
        "net_profit_r": round(sum(t["r_multiple"] for t in trades), 3),
        "average_r_per_trade": round(
            sum(t["r_multiple"] for t in trades) / total, 3
        ) if total else 0.0,
        "maximum_drawdown_r": round(max_drawdown, 3),
        "tp1_hit_rate_percent": round(
            sum(t["highest_target"] >= 1 for t in trades) / total * 100, 2
        ) if total else 0.0,
        "tp2_hit_rate_percent": round(
            sum(t["highest_target"] >= 2 for t in trades) / total * 100, 2
        ) if total else 0.0,
        "tp3_hit_rate_percent": round(
            sum(t["highest_target"] >= 3 for t in trades) / total * 100, 2
        ) if total else 0.0,
        "stop_loss_rate_percent": round(
            sum(t["exit_reason"] in ("STOP_LOSS", "STOP_LOSS_GAP") for t in trades)
            / total * 100, 2
        ) if total else 0.0,
        "costs_included": False,
        "performance_basis": "Gross R multiples; spread, slippage and commissions are not included.",
        "trades": trades,
    }


def run_backtest_v2(
    candles_by_timeframe: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """
    Backtest the combined V2 precision strategy on synchronized Gold candles.

    A signal is evaluated at a 5M candle close. Entry is the next 5M candle
    open. Higher-timeframe candles are filtered by their actual close time,
    preventing the use of unfinished or future candles.
    """
    normalised = {
        timeframe: _normalise_candles(
            candles_by_timeframe.get(timeframe, []), timeframe
        )
        for timeframe in ALL_TIMEFRAMES
    }
    candles_5m = normalised["5M"]
    data_gaps = {
        timeframe: _count_gaps(
            normalised[timeframe], TIMEFRAME_SECONDS[timeframe]
        )
        for timeframe in ALL_TIMEFRAMES
    }

    if len(candles_5m) < MIN_5M_HISTORY:
        return {
            "strategy": "RevAI Gold Precision Engine V2",
            "status": "INSUFFICIENT_DATA",
            "candles_tested": len(candles_5m),
            "data_gaps_detected": data_gaps,
            "message": f"At least {MIN_5M_HISTORY} 5M candles are required.",
        }

    trades: list[dict[str, Any]] = []
    skipped_reasons: Counter = Counter()
    rejected_entries = 0
    index = 0
    duration_5m = TIMEFRAME_SECONDS["5M"]

    while index < len(candles_5m) - 1:
        signal_epoch = candles_5m[index]["epoch"] + duration_5m
        history = _closed_history(normalised, signal_epoch)

        ready, reason = _data_ready(history, signal_epoch)
        if not ready:
            skipped_reasons[reason or "DATA_NOT_READY"] += 1
            index += 1
            continue

        # Do not create a signal if the just-closed 5M candle is separated
        # from the prior one by a missing interval.
        if index > 0 and (
            candles_5m[index]["epoch"] - candles_5m[index - 1]["epoch"]
            != duration_5m
        ):
            skipped_reasons["SIGNAL_CANDLE_AFTER_5M_GAP"] += 1
            index += 1
            continue

        analysis = analyse_precision_opportunity(history, signal_epoch)
        if analysis.get("signal") not in ("BUY", "SELL") or not analysis.get("qualified"):
            skipped_reasons[analysis.get("reason", "NO_QUALIFIED_SETUP")] += 1
            index += 1
            continue

        entry_index = index + 1
        entry_candle = candles_5m[entry_index]
        if entry_candle["epoch"] != signal_epoch:
            skipped_reasons["NO_CONTIGUOUS_NEXT_5M_ENTRY"] += 1
            index += 1
            continue

        trade = _make_trade(analysis, entry_candle, entry_candle["epoch"])
        if trade is None:
            rejected_entries += 1
            skipped_reasons["INVALID_NEXT_OPEN_ENTRY_OR_STOP"] += 1
            index += 1
            continue

        completed, exit_index = _simulate_trade(
            trade, candles_5m, entry_index
        )
        if completed["exit_reason"] == "NO_FUTURE_CANDLE":
            skipped_reasons["NO_FUTURE_CANDLE_TO_EVALUATE"] += 1
            index += 1
            continue

        trades.append(completed)
        # One combined precision trade at a time.
        index = max(exit_index + 1, entry_index + 1)

    return calculate_v2_metrics(
        candles_5m,
        trades,
        data_gaps=data_gaps,
        skipped_reasons=skipped_reasons,
        rejected_entries=rejected_entries,
    )
