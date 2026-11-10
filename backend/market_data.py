
import asyncio
import json
import math
import websockets

from typing import Any, Optional

DERIV_WS_URL = "wss://api.derivws.com/trading/v1/options/ws/public"

GOLD_SYMBOL = "frxXAUUSD"

TIMEFRAMES = {
    "1D": 86400,
    "4H": 14400,
    "1H": 3600,
    "15M": 900,
    "5M": 300,
}

PAGE_SIZE = 500
MAX_PAGES = 20
EXTENDED_GAP_SECONDS = 6 * 60 * 60


async def _receive_response(
    websocket: Any,
    req_id: int,
    timeout: int = 30,
) -> dict[str, Any]:

    while True:
        message = await asyncio.wait_for(
            websocket.recv(),
            timeout=timeout,
        )

        response = json.loads(message)

        if response.get("req_id") == req_id:

            if "error" in response:
                raise RuntimeError(
                    response["error"].get(
                        "message",
                        "Deriv API error"
                    )
                )

            return response


def validate_candles(
    candles: list[dict[str, Any]],
    timeframe: str,
) -> dict[str, Any]:

    granularity = TIMEFRAMES[timeframe]

    unique_candles = {}
    duplicate_count = 0
    misaligned_candles = []
    invalid_ohlc_candles = []

    for candle in candles:

        try:
            epoch = int(candle["epoch"])

            open_price = float(candle["open"])
            high_price = float(candle["high"])
            low_price = float(candle["low"])
            close_price = float(candle["close"])

        except (KeyError, TypeError, ValueError, OverflowError):
            invalid_ohlc_candles.append({
                "reason": "Missing or invalid candle fields",
                "candle": candle,
            })
            continue

        prices = [
            open_price,
            high_price,
            low_price,
            close_price,
        ]

        if not all(math.isfinite(price) for price in prices):
            invalid_ohlc_candles.append({
                "reason": "Non-finite OHLC price",
                "candle": candle,
            })
            continue

        if (
            high_price < low_price
            or high_price < max(open_price, close_price)
            or low_price > min(open_price, close_price)
        ):
            invalid_ohlc_candles.append({
                "reason": "Invalid OHLC relationship",
                "candle": candle,
            })
            continue

        normalized = {
            "epoch": epoch,
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
        }

        if epoch in unique_candles:
            duplicate_count += 1
            continue

        unique_candles[epoch] = normalized

    valid_candles = []
    rejected_candles = []

    for epoch in sorted(unique_candles):

        candle = unique_candles[epoch]

        if epoch % granularity != 0:
            rejected_candles.append({
                "reason": "Timestamp not aligned to timeframe",
                "candle": candle,
            })
            misaligned_candles.append(candle)
            continue

        valid_candles.append(candle)

    gaps = []

    for index in range(1, len(valid_candles)):

        previous_epoch = valid_candles[index - 1]["epoch"]
        current_epoch = valid_candles[index]["epoch"]

        difference = current_epoch - previous_epoch

        if difference > granularity:

            missing_intervals = max(
                0,
                (difference // granularity) - 1,
            )

            gap_type = (
                "EXTENDED_GAP"
                if difference >= EXTENDED_GAP_SECONDS
                else "SHORT_GAP"
            )

            gaps.append({
                "from_epoch": previous_epoch,
                "to_epoch": current_epoch,
                "gap_seconds": difference,
                "missing_intervals_estimate": missing_intervals,
                "classification": gap_type,
            })

    return {
        "candles": valid_candles,
        "data_quality": {
            "timeframe": timeframe,
            "granularity_seconds": granularity,
            "raw_received": len(candles),
            "valid_received": len(valid_candles),
            "excluded_count": (
                len(rejected_candles)
                + len(invalid_ohlc_candles)
            ),
            "duplicate_count": duplicate_count,
            "misaligned_count": len(misaligned_candles),
            "invalid_ohlc_count": len(invalid_ohlc_candles),
            "gap_count": len(gaps),
            "gaps": gaps,
            "rejected_candles": rejected_candles,
            "invalid_ohlc_candles": invalid_ohlc_candles,
        },
    }


async def get_gold_candles(
    timeframe: str,
    count: int = 500,
) -> dict[str, Any]:

    if timeframe not in TIMEFRAMES:
        raise ValueError("Unsupported timeframe")

    if count < 1:
        raise ValueError("Count must be greater than zero")

    granularity = TIMEFRAMES[timeframe]

    all_candles = {}
    cursor: Optional[int] = None
    pages = 0

    async with websockets.connect(
        DERIV_WS_URL,
        open_timeout=15,
        close_timeout=10,
        ping_interval=20,
        ping_timeout=20,
    ) as websocket:

        while len(all_candles) < count:

            if pages >= MAX_PAGES:
                break

            remaining = count - len(all_candles)

            batch_size = min(
                PAGE_SIZE,
                remaining,
            )

            req_id = pages + 1

            request = {
                "ticks_history": GOLD_SYMBOL,
                "count": batch_size,
                "end": (
                    cursor
                    if cursor is not None
                    else "latest"
                ),
                "style": "candles",
                "granularity": granularity,
                "req_id": req_id,
            }

            await websocket.send(json.dumps(request))

            response = await _receive_response(
                websocket,
                req_id,
            )

            candles = response.get("candles", [])

            if not candles:
                break

            new_candles = 0

            for candle in candles:

                epoch = int(candle["epoch"])

                if epoch not in all_candles:
                    all_candles[epoch] = candle
                    new_candles += 1

            pages += 1

            if new_candles == 0:
                break

            oldest_epoch = min(
                int(candle["epoch"])
                for candle in candles
            )

            cursor = oldest_epoch - 1

    raw_candles = [
        all_candles[epoch]
        for epoch in sorted(all_candles)
    ]

    validation = validate_candles(
        raw_candles,
        timeframe,
    )

    return {
        "symbol": GOLD_SYMBOL,
        "timeframe": timeframe,
        "requested": count,
        "received": len(validation["candles"]),
        "raw_received": len(raw_candles),
        "pages_fetched": pages,

        # Reaching the requested count does not prove
        # that Deriv has additional historical candles.
        "has_more_history": None,

        "candles": validation["candles"],
        "data_quality": validation["data_quality"],
    }


async def get_all_gold_candles(
    count: int = 500,
) -> dict[str, Any]:

    results = {}

    for timeframe in TIMEFRAMES:

        results[timeframe] = await get_gold_candles(
            timeframe,
            count=count,
        )

    return results
