
from __future__ import annotations

from typing import Any

from signal_engine import analyse_timeframe


TIMEFRAMES = ["1D", "4H", "1H", "15M", "5M"]

MAX_HOLDING_BARS = 30


def _timeframe_seconds(timeframe: str) -> int:
    durations = {
        "1D": 86400,
        "4H": 14400,
        "1H": 3600,
        "15M": 900,
        "5M": 300,
    }

    if timeframe not in durations:
        raise ValueError("Unsupported timeframe")

    return durations[timeframe]


def _count_data_gaps(
    candles: list[dict[str, Any]],
    duration: int,
) -> int:
    gaps = 0

    for previous, current in zip(candles, candles[1:]):
        difference = current["epoch"] - previous["epoch"]

        if difference != duration:
            gaps += 1

    return gaps


def _has_contiguous_lookback(
    candles: list[dict[str, Any]],
    index: int,
    duration: int,
    lookback: int = 30,
) -> bool:
    if index < lookback:
        return False

    recent = candles[index - lookback:index + 1]

    for previous, current in zip(recent, recent[1:]):
        if current["epoch"] - previous["epoch"] != duration:
            return False

    return True


def run_backtest(
    candles: list[dict[str, Any]],
    timeframe: str,
) -> dict[str, Any]:

    duration = _timeframe_seconds(timeframe)

    candles = sorted(
        candles,
        key=lambda candle: candle["epoch"]
    )

    # Remove duplicate timestamps before testing.
    unique_candles = {}

    for candle in candles:
        unique_candles[candle["epoch"]] = candle

    candles = [
        unique_candles[epoch]
        for epoch in sorted(unique_candles)
    ]

    data_gaps = _count_data_gaps(candles, duration)

    if len(candles) < 50:
        return {
            "timeframe": timeframe,
            "status": "INSUFFICIENT_DATA",
            "candles_tested": len(candles),
            "data_gaps_detected": data_gaps,
            "message": "At least 50 candles are required.",
        }

    trades = []
    index = 30

    skipped_gap_setups = 0
    data_gap_exits = 0

    max_holding_seconds = MAX_HOLDING_BARS * duration

    while index < len(candles) - 1:

        # Do not generate signals from a lookback window
        # containing missing or irregularly spaced candles.
        if not _has_contiguous_lookback(
            candles,
            index,
            duration,
        ):
            skipped_gap_setups += 1
            index += 1
            continue

        # Signal is evaluated at the close of the current candle.
        signal_epoch = candles[index]["epoch"] + duration

        historical_candles = candles[:index + 1]

        analysis = analyse_timeframe(
            historical_candles,
            timeframe,
            as_of_epoch=signal_epoch,
        )

        direction = analysis.get("signal")

        if direction not in ("BUY", "SELL"):
            index += 1
            continue

        entry = analysis["entry"]
        stop = analysis["stop_loss"]
        tp1 = analysis["tp1"]
        tp2 = analysis["tp2"]
        tp3 = analysis["tp3"]

        risk = abs(entry - stop)

        if risk <= 0:
            index += 1
            continue

        exit_price = None
        exit_reason = "TIMEOUT"
        highest_target = 0
        actual_exit_index = None

        # Enforce the maximum holding period using real elapsed time.
        expiry_epoch = signal_epoch + max_holding_seconds

        last_eligible_index = index

        for future_index in range(index + 1, len(candles)):

            candle = candles[future_index]

            # Do not process candles beyond the holding deadline.
            if candle["epoch"] >= expiry_epoch:
                break

            previous_candle = candles[future_index - 1]

            # A missing interval means the price path is unknown.
            # Close at the first available opening price after the gap.
            if candle["epoch"] - previous_candle["epoch"] != duration:

                exit_price = candle["open"]
                exit_reason = "DATA_GAP_EXIT"
                actual_exit_index = future_index
                data_gap_exits += 1
                break

            last_eligible_index = future_index

            high = candle["high"]
            low = candle["low"]
            open_price = candle["open"]

            if direction == "BUY":

                # Account for adverse gaps through the opening price.
                if open_price <= stop:
                    exit_price = open_price
                    exit_reason = "STOP_LOSS_GAP"
                    actual_exit_index = future_index
                    break

                if open_price >= tp3:
                    exit_price = open_price
                    exit_reason = "TP3"
                    highest_target = 3
                    actual_exit_index = future_index
                    break

                # Conservative assumption: stop wins if both
                # stop and target are touched in the same candle.
                if low <= stop:
                    exit_price = stop
                    exit_reason = "STOP_LOSS"
                    actual_exit_index = future_index
                    break

                if high >= tp1:
                    highest_target = max(highest_target, 1)

                if high >= tp2:
                    highest_target = max(highest_target, 2)

                if high >= tp3:
                    highest_target = 3
                    exit_price = tp3
                    exit_reason = "TP3"
                    actual_exit_index = future_index
                    break

            else:

                if open_price >= stop:
                    exit_price = open_price
                    exit_reason = "STOP_LOSS_GAP"
                    actual_exit_index = future_index
                    break

                if open_price <= tp3:
                    exit_price = open_price
                    exit_reason = "TP3"
                    highest_target = 3
                    actual_exit_index = future_index
                    break

                if high >= stop:
                    exit_price = stop
                    exit_reason = "STOP_LOSS"
                    actual_exit_index = future_index
                    break

                if low <= tp1:
                    highest_target = max(highest_target, 1)

                if low <= tp2:
                    highest_target = max(highest_target, 2)

                if low <= tp3:
                    highest_target = 3
                    exit_price = tp3
                    exit_reason = "TP3"
                    actual_exit_index = future_index
                    break

        if exit_price is None:

            # Use the last available candle within the time limit.
            if last_eligible_index == index:
                index += 1
                continue

            actual_exit_index = last_eligible_index
            exit_price = candles[actual_exit_index]["close"]

            if highest_target == 0:
                exit_reason = "TIMEOUT"
            else:
                exit_reason = f"TIMEOUT_AFTER_TP{highest_target}"

        if direction == "BUY":
            profit = exit_price - entry
        else:
            profit = entry - exit_price

        r_multiple = profit / risk

        # A DATA_GAP_EXIT executes at the first available candle open.
        # Other exits are represented at the candle close because OHLC
        # data cannot reveal the exact intrabar execution timestamp.
        if exit_reason == "DATA_GAP_EXIT":
            exit_epoch = candles[actual_exit_index]["epoch"]
        else:
            exit_epoch = candles[actual_exit_index]["epoch"] + duration

        trades.append({
            "timeframe": timeframe,
            "direction": direction,
            "entry": round(entry, 2),
            "stop_loss": round(stop, 2),
            "tp1": round(tp1, 2),
            "tp2": round(tp2, 2),
            "tp3": round(tp3, 2),
            "exit_price": round(exit_price, 2),
            "exit_reason": exit_reason,
            "highest_target": highest_target,
            "r_multiple": round(r_multiple, 3),
            "entry_epoch": signal_epoch,
            "exit_epoch": exit_epoch,
        })

        # One trade at a time per timeframe.
        index = actual_exit_index + 1

    return calculate_metrics(
        timeframe,
        candles,
        trades,
        data_gaps_detected=data_gaps,
        skipped_gap_setups=skipped_gap_setups,
        data_gap_exits=data_gap_exits,
    )


def calculate_metrics(
    timeframe: str,
    candles: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    data_gaps_detected: int = 0,
    skipped_gap_setups: int = 0,
    data_gap_exits: int = 0,
) -> dict[str, Any]:

    total = len(trades)

    if total == 0:
        return {
            "timeframe": timeframe,
            "status": "NO_TRADES",
            "candles_tested": len(candles),
            "data_gaps_detected": data_gaps_detected,
            "skipped_gap_setups": skipped_gap_setups,
            "data_gap_exits": data_gap_exits,
            "total_trades": 0,
            "message": "No qualified setups found.",
        }

    wins = sum(
        1 for trade in trades
        if trade["r_multiple"] > 0
    )

    losses = sum(
        1 for trade in trades
        if trade["r_multiple"] < 0
    )

    breakeven = total - wins - losses

    total_profit = sum(
        trade["r_multiple"]
        for trade in trades
        if trade["r_multiple"] > 0
    )

    total_loss = abs(sum(
        trade["r_multiple"]
        for trade in trades
        if trade["r_multiple"] < 0
    ))

    profit_factor = (
        total_profit / total_loss
        if total_loss > 0
        else None
    )

    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0

    for trade in trades:
        equity += trade["r_multiple"]
        peak = max(peak, equity)

        drawdown = peak - equity
        max_drawdown = max(max_drawdown, drawdown)

    tp1_hits = sum(
        1 for trade in trades
        if trade["highest_target"] >= 1
    )

    tp2_hits = sum(
        1 for trade in trades
        if trade["highest_target"] >= 2
    )

    tp3_hits = sum(
        1 for trade in trades
        if trade["highest_target"] >= 3
    )

    stop_losses = sum(
        1 for trade in trades
        if trade["exit_reason"] in (
            "STOP_LOSS",
            "STOP_LOSS_GAP",
        )
    )

    gap_exit_trades = [
        trade for trade in trades
        if trade["exit_reason"] == "DATA_GAP_EXIT"
    ]
    gap_exit_wins = sum(
        1 for trade in gap_exit_trades
        if trade["r_multiple"] > 0
    )
    gap_exit_losses = sum(
        1 for trade in gap_exit_trades
        if trade["r_multiple"] < 0
    )

    return {
        "timeframe": timeframe,
        "status": "COMPLETED",
        "candles_tested": len(candles),
        "data_gaps_detected": data_gaps_detected,
        "skipped_gap_setups": skipped_gap_setups,
        "data_gap_exits": data_gap_exits,
        "data_gap_exit_wins": gap_exit_wins,
        "data_gap_exit_losses": gap_exit_losses,
        "data_gap_exit_breakeven": (
            len(gap_exit_trades) - gap_exit_wins - gap_exit_losses
        ),
        "maximum_holding_bars": MAX_HOLDING_BARS,
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "breakeven_trades": breakeven,
        "win_rate_percent": round(
            (wins / total) * 100, 2
        ),
        "profit_factor": (
            round(profit_factor, 3)
            if profit_factor is not None
            else None
        ),
        "net_profit_r": round(
            sum(trade["r_multiple"] for trade in trades),
            3,
        ),
        "average_r_per_trade": round(
            sum(trade["r_multiple"] for trade in trades) / total,
            3,
        ),
        "maximum_drawdown_r": round(
            max_drawdown, 3
        ),
        "tp1_hit_rate_percent": round(
            (tp1_hits / total) * 100, 2
        ),
        "tp2_hit_rate_percent": round(
            (tp2_hits / total) * 100, 2
        ),
        "tp3_hit_rate_percent": round(
            (tp3_hits / total) * 100, 2
        ),
        "stop_loss_rate_percent": round(
            (stop_losses / total) * 100, 2
        ),
        "trades": trades,
    }
