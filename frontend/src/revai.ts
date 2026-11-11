
export const REVAI_API = (
  import.meta.env.VITE_API_URL || "http://localhost:8000"
).replace(/\/$/, "")

export interface TimeframeContext {
  timeframe: string
  trend: string
  ready: boolean
  close: number
  ema20: number
  ema50: number
  rsi: number
  atr: number
  closed_candles: number
  candle_epoch: number
}

export interface PrecisionSignal {
  timeframe: string
  signal: 'BUY' | 'SELL' | 'WAIT'
  qualified: boolean
  reason: string
  direction_bias?: string
  context?: Record<string, TimeframeContext>
  setup_15m?: {
    qualified: boolean
    setup: string
    pullback: boolean
    liquidity_sweep: boolean
    confirmation_candle: boolean
    reason: string
    candle_epoch: number
    atr: number
  }
  entry?: number
  stop_loss?: number
  take_profit_1?: number
  take_profit_2?: number
  take_profit_3?: number
}

export interface TimeframeSignal {
  timeframe: string
  signal: 'BUY' | 'SELL' | 'WAIT'
  reason: string
  entry?: number
  stop_loss?: number
  tp1?: number
  tp2?: number
  tp3?: number
  buy_score?: number
  sell_score?: number
  rsi?: number
  atr?: number
  candles_received?: number
  closed_candles?: number
  analysis?: {
    ema9?: number
    ema21?: number
    latest_close?: number
    previous_high?: number
    previous_low?: number
    rsi?: number
    atr?: number
    bullish_momentum?: boolean
    bearish_momentum?: boolean
    bullish_confirmation?: boolean
    bearish_confirmation?: boolean
    buy_checks?: Record<string, boolean>
    sell_checks?: Record<string, boolean>
    buy_reasons?: string[]
    buy_failed_checks?: string[]
    sell_reasons?: string[]
    sell_failed_checks?: string[]
  }
}

export interface PrecisionResponse {
  platform: string
  symbol: string
  engine: string
  mode: string
  timestamp: number
  signal?: PrecisionSignal
  signals: Record<string, TimeframeSignal>
  data_quality: Record<string, {
    requested: number
    received: number
    pages_fetched: number
    data_quality: {
      valid_received: number
      gap_count: number
      misaligned_count: number
    }
  }>
}

export async function fetchPrecisionSignal(): Promise<PrecisionResponse> {
  const response = await fetch(`${REVAI_API}/api/signals/precision`)

  if (!response.ok) {
    throw new Error(`RevAI API error: HTTP ${response.status}`)
  }

  return response.json()
}
