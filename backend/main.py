import time
import sqlite3
from pathlib import Path

from backtest import run_backtest
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from market_data import (
    get_gold_candles,
    get_all_gold_candles,
    TIMEFRAMES,
)

from signal_engine import analyse_timeframe
from signal_engine_v2 import analyse_precision_opportunity



# Persistent signal history
HISTORY_DB = Path(__file__).with_name("revai_history.db")

def init_history_db():
    """Create history storage and safely migrate databases created by older versions."""
    with sqlite3.connect(HISTORY_DB) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS signal_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_key TEXT UNIQUE NOT NULL,
                symbol TEXT NOT NULL,
                issued_at INTEGER NOT NULL,
                timeframe TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry REAL NOT NULL,
                stop_loss REAL NOT NULL,
                tp1 REAL,
                tp2 REAL,
                tp3 REAL,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                exit_price REAL,
                closed_at INTEGER,
                expiry_epoch INTEGER NOT NULL,
                last_checked_epoch INTEGER NOT NULL,
                validity_status TEXT NOT NULL DEFAULT 'ACTIVE',
                outcome_status TEXT NOT NULL DEFAULT 'MONITORING',
                expired_at INTEGER
            )
        """)

        # Add columns to databases created before outcome tracking was separated
        # from signal validity. Existing expired rows remain expired but are
        # eligible for continued outcome monitoring.
        columns = {
            row[1] for row in db.execute("PRAGMA table_info(signal_history)")
        }
        migrations = {
            "validity_status": "ALTER TABLE signal_history ADD COLUMN validity_status TEXT NOT NULL DEFAULT 'ACTIVE'",
            "outcome_status": "ALTER TABLE signal_history ADD COLUMN outcome_status TEXT NOT NULL DEFAULT 'MONITORING'",
            "expired_at": "ALTER TABLE signal_history ADD COLUMN expired_at INTEGER",
            "tracking_enabled": "ALTER TABLE signal_history ADD COLUMN tracking_enabled INTEGER NOT NULL DEFAULT 0",
        }
        for column, sql in migrations.items():
            if column not in columns:
                db.execute(sql)

        db.commit()

def monitor_signal_history(candles_by_timeframe, as_of_epoch):
    """
    Monitor outcomes independently of signal validity.

    A signal can be EXPIRED for validity while its original entry/targets are
    still monitored against subsequent completed candles. The outcome is stored
    separately so expiry never erases a later TP/SL result.
    """
    init_history_db()

    with sqlite3.connect(HISTORY_DB) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("""
            SELECT * FROM signal_history
            WHERE tracking_enabled = 1
              AND outcome_status IN ('MONITORING', 'TP1_HIT', 'TP2_HIT')
        """).fetchall()

        for row in rows:
            timeframe = row["timeframe"]
            candles = candles_by_timeframe.get(timeframe, [])
            later_candles = sorted(
                (
                    c for c in candles
                    if row["last_checked_epoch"] < int(c["epoch"])
                    and int(c["epoch"]) + TIMEFRAMES[timeframe] <= as_of_epoch
                ),
                key=lambda c: int(c["epoch"])
            )

            outcome = row["outcome_status"] or "MONITORING"
            exit_price = row["exit_price"]
            closed_at = row["closed_at"]
            last_checked = row["last_checked_epoch"]

            for candle in later_candles:
                high = float(candle["high"])
                low = float(candle["low"])
                direction = row["direction"]

                # Conservative assumption: stop wins if stop and a target
                # are both touched inside the same candle.
                stop_hit = (
                    low <= row["stop_loss"] if direction == "BUY"
                    else high >= row["stop_loss"]
                )
                if stop_hit:
                    outcome = "STOP_LOSS_HIT"
                    exit_price = row["stop_loss"]
                    closed_at = int(candle["epoch"])
                    last_checked = int(candle["epoch"])
                    break

                targets = [
                    ("TP1_HIT", row["tp1"]),
                    ("TP2_HIT", row["tp2"]),
                    ("TP3_HIT", row["tp3"]),
                ]
                target_order = {
                    "MONITORING": 0,
                    "TP1_HIT": 1,
                    "TP2_HIT": 2,
                    "TP3_HIT": 3,
                }
                reached = []
                for target_status, target in targets:
                    if target is None:
                        continue
                    target_hit = (
                        high >= target if direction == "BUY"
                        else low <= target
                    )
                    if target_hit:
                        reached.append(target_status)

                # Advance to the furthest target touched in this candle.
                if reached:
                    furthest = max(reached, key=lambda item: target_order[item])
                    if target_order[furthest] > target_order.get(outcome, 0):
                        outcome = furthest
                        # Use the stored target price directly.
                        exit_price = {
                            "TP1_HIT": row["tp1"],
                            "TP2_HIT": row["tp2"],
                            "TP3_HIT": row["tp3"],
                        }[furthest]
                        if furthest == "TP3_HIT":
                            closed_at = int(candle["epoch"])

                last_checked = int(candle["epoch"])
                if outcome in ("TP3_HIT", "STOP_LOSS_HIT"):
                    break

            validity = row["validity_status"] or "ACTIVE"
            expired_at = row["expired_at"]
            if validity == "ACTIVE" and as_of_epoch >= row["expiry_epoch"]:
                validity = "EXPIRED"
                expired_at = as_of_epoch

            # Keep the legacy status field usable by the existing History UI:
            # while still monitoring, it shows EXPIRED after validity expires;
            # once a TP/SL outcome is reached, it shows that outcome.
            if outcome in ("TP1_HIT", "TP2_HIT", "TP3_HIT", "STOP_LOSS_HIT"):
                display_status = outcome
            else:
                display_status = validity

            db.execute("""
                UPDATE signal_history
                SET status = ?, validity_status = ?, outcome_status = ?,
                    exit_price = ?, closed_at = ?, expired_at = ?,
                    last_checked_epoch = ?
                WHERE id = ?
            """, (
                display_status, validity, outcome, exit_price, closed_at,
                expired_at, last_checked, row["id"]
            ))

        db.commit()

def record_qualified_signals(signals, candles_by_timeframe, as_of_epoch):
    init_history_db()

    with sqlite3.connect(HISTORY_DB) as db:
        for timeframe, item in signals.items():
            direction = item.get("signal")

            if direction not in ("BUY", "SELL"):
                continue

            duration = TIMEFRAMES[timeframe]
            closed = [
                c for c in candles_by_timeframe.get(timeframe, [])
                if int(c["epoch"]) + duration <= as_of_epoch
            ]

            if not closed:
                continue

            signal_epoch = int(closed[-1]["epoch"])
            signal_key = f"XAUUSD:{timeframe}:{direction}:{signal_epoch}"

            higher_tf = {
                "4H": "1D", "1H": "4H", "15M": "1H", "5M": "15M"
            }.get(timeframe)
            higher_direction = (
                signals.get(higher_tf, {}).get("signal")
                if higher_tf else None
            )

            signal_type = (
                "COUNTERTREND"
                if higher_direction in ("BUY", "SELL")
                and higher_direction != direction
                else "QUICK SCALP"
                if timeframe in ("5M", "15M")
                else "TREND"
            )

            required = ("entry", "stop_loss", "tp1", "tp2", "tp3")
            if any(item.get(field) is None for field in required):
                continue

            db.execute("""
                INSERT OR IGNORE INTO signal_history (
                    signal_key, symbol, issued_at, timeframe, signal_type,
                    direction, entry, stop_loss, tp1, tp2, tp3,
                    status, expiry_epoch, last_checked_epoch,
                    validity_status, outcome_status, tracking_enabled
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, 'ACTIVE', 'MONITORING', 1)
            """, (
                signal_key, "XAU/USD", signal_epoch, timeframe, signal_type,
                direction, item["entry"], item["stop_loss"],
                item["tp1"], item["tp2"], item["tp3"],
                signal_epoch + (duration * 3), signal_epoch
            ))

        db.commit()

    monitor_signal_history(candles_by_timeframe, as_of_epoch)


app = FastAPI(title="RevAI API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://rev-ai-gilt.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def home():
    return {"message": "RevAI backend is running"}


@app.get("/api/health")
def health():
    return {"status": "online", "platform": "RevAI"}


@app.get("/api/market/gold/{timeframe}")
async def gold_market_data(timeframe: str):
    timeframe = timeframe.upper()

    if timeframe not in TIMEFRAMES:
        raise HTTPException(
            status_code=400,
            detail="Supported timeframes: 1D, 4H, 1H, 15M, 5M"
        )

    try:
        return await get_gold_candles(timeframe, count=500)
    except Exception as error:
        raise HTTPException(status_code=502, detail=str(error))


@app.get("/api/market/gold")
async def all_gold_market_data():
    try:
        return await get_all_gold_candles()
    except Exception as error:
        raise HTTPException(status_code=502, detail=str(error))


@app.get("/api/signals/preview")
async def preview_signals():
    try:
        market_data = await get_all_gold_candles()

        signals = {}

        for timeframe, result in market_data.items():
            signals[timeframe] = analyse_timeframe(
                result["candles"],
                timeframe
            )

        return {
            "platform": "RevAI",
            "symbol": "XAU/USD",
            "mode": "RESEARCH_PREVIEW",
            "signals": signals,
        }

    except Exception as error:
        raise HTTPException(status_code=502, detail=str(error))
@app.get("/api/backtest/{timeframe}")
async def backtest_timeframe(timeframe: str):
    timeframe = timeframe.upper()

    if timeframe not in TIMEFRAMES:
        raise HTTPException(
            status_code=400,
            detail="Supported timeframes: 1D, 4H, 1H, 15M, 5M"
        )

    try:
        market_data = await get_gold_candles(
            timeframe,
            count=500
        )

        return run_backtest(
            market_data["candles"],
            timeframe
        )

    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=str(error)
        )

@app.get("/api/signals/precision")
async def precision_signal():
    try:
        market_data = await get_all_gold_candles(count=500)
        as_of_epoch = int(time.time())

        candles_by_timeframe = {
            timeframe: result["candles"]
            for timeframe, result in market_data.items()
        }

        from signal_engine import analyse_timeframe

        # Each Gold timeframe generates its own independent signal.
        signals = {
            timeframe: analyse_timeframe(
                candles_by_timeframe.get(timeframe, []),
                timeframe,
                as_of_epoch
            )
            for timeframe in ("1D", "4H", "1H", "15M", "5M")
        }

        record_qualified_signals(signals, candles_by_timeframe, as_of_epoch)

        data_quality = {
            timeframe: {
                "requested": result.get("requested"),
                "received": result.get("received"),
                "pages_fetched": result.get("pages_fetched"),
                "data_quality": result.get("data_quality"),
            }
            for timeframe, result in market_data.items()
        }

        return {
            "platform": "RevAI",
            "symbol": "XAU/USD",
            "engine": "Independent Timeframe Signal Engine",
            "mode": "PAPER_TRADING_PREVIEW",
            "timestamp": as_of_epoch,
            "signals": signals,
            "data_quality": data_quality,
        }

    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=502, detail=str(error))


@app.get("/api/signals/history")
async def signal_history(page: int = 1):
    init_history_db()

    limit = 10
    page = max(1, page)
    offset = (page - 1) * limit

    with sqlite3.connect(HISTORY_DB) as db:
        db.row_factory = sqlite3.Row

        total = db.execute(
            "SELECT COUNT(*) FROM signal_history"
        ).fetchone()[0]

        pages = max(1, (total + limit - 1) // limit)
        page = min(page, pages)
        offset = (page - 1) * limit

        rows = db.execute("""
            SELECT * FROM signal_history
            ORDER BY issued_at DESC
            LIMIT ? OFFSET ?
        """, (limit, offset)).fetchall()

        records = [dict(row) for row in rows]

        summary = db.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status IN ('ACTIVE', 'TP1_HIT', 'TP2_HIT') THEN 1 ELSE 0 END) AS active,
                SUM(CASE WHEN status = 'TP1_HIT' THEN 1 ELSE 0 END) AS tp1,
                SUM(CASE WHEN status = 'TP2_HIT' THEN 1 ELSE 0 END) AS tp2,
                SUM(CASE WHEN status = 'TP3_HIT' THEN 1 ELSE 0 END) AS tp3,
                SUM(CASE WHEN status = 'STOP_LOSS_HIT' THEN 1 ELSE 0 END) AS stop_loss,
                SUM(CASE WHEN validity_status = 'EXPIRED' THEN 1 ELSE 0 END) AS expired,
                SUM(CASE WHEN outcome_status = 'MONITORING' THEN 1 ELSE 0 END) AS monitoring,
                SUM(CASE WHEN outcome_status = 'STOP_LOSS_HIT' THEN 1 ELSE 0 END) AS outcomes_stop_loss
            FROM signal_history
        """).fetchone()

    return {
        "symbol": "XAU/USD",
        "total": total,
        "page": page,
        "limit": limit,
        "pages": pages,
        "summary": dict(summary),
        "records": records
    }
