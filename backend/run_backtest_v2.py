from __future__ import annotations

import asyncio
import json

from market_data import get_all_gold_candles
from backtest_v2 import run_backtest_v2


async def main() -> None:
    print("Fetching Gold historical candles from Deriv...")
    market_data = await get_all_gold_candles(count=5000)

    candles_by_timeframe = {
        timeframe: result.get("candles", [])
        for timeframe, result in market_data.items()
    }

    print("Running RevAI Gold Precision Engine V2 backtest...")
    result = run_backtest_v2(candles_by_timeframe)

    summary = {
        key: value
        for key, value in result.items()
        if key != "trades"
    }

    summary["market_data"] = {
        timeframe: {
            "requested": payload.get("requested"),
            "received": payload.get("received"),
            "raw_received": payload.get("raw_received"),
            "pages_fetched": payload.get("pages_fetched"),
            "data_quality": payload.get("data_quality"),
        }
        for timeframe, payload in market_data.items()
    }

    print("\n========== REVAI V2 BACKTEST RESULTS ==========")
    print(json.dumps(summary, indent=2, default=str))

    result["market_data"] = summary["market_data"]

    with open("backtest_v2_results.json", "w", encoding="utf-8") as file:
        json.dump(result, file, indent=2, default=str)

    print("\nFull results saved to backtest_v2_results.json")


if __name__ == "__main__":
    asyncio.run(main())