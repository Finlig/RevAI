const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000"
export const REVAI_API = apiUrl.endsWith("/") ? apiUrl.slice(0, -1) : apiUrl

export interface TimeframeContext {
  timeframe: string
  trend: string
  ready: boolean
  reason?: string
  close?: number
  ema20?: number
  ema50?: number
  rsi?: number
  atr?: number
  closed_candles?: number
  candle_epoch?: number
}

export interface SignalChecks {
  [name: string]: boolean
}

export interface PrecisionSignal {
  timeframe: string
  signal: 'BUY' | 'SELL' | 'WAIT'
  qualified: boolean
  reason: string
  direction_bias?: string
  classification?: string
  setup_type?: string
  quality_tier?: 'QUICK SCALP' | 'STANDARD' | 'SNIPER' | string
  market_condition?: string
  classification_details?: {
    setup_type?: string
    quality_tier?: string
    market_condition?: string
    volatility_ratio?: number
    market_structure?: {
      ready?: boolean
      breakout?: boolean
      retest?: boolean
      swing_break?: boolean
      prior_range_high?: number
      prior_range_low?: number
      broken_level?: number
    }
    higher_timeframe_alignment?: { matching?: number; opposing?: boolean }
  }
  entry?: number
  stop_loss?: number
  tp1?: number
  tp2?: number
  tp3?: number
  buy_score?: number
  sell_score?: number
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
    buy_checks?: SignalChecks
    sell_checks?: SignalChecks
    buy_reasons?: string[]
    sell_reasons?: string[]
    buy_failed_checks?: string[]
    sell_failed_checks?: string[]
  }
  context?: Record<string, TimeframeContext>
  setup_15m?: {
    qualified: boolean
    setup?: string
    reason: string
    buy_score?: number
    sell_score?: number
    analysis?: PrecisionSignal['analysis']
  }
  confirmation_5m?: {
    qualified: boolean
    reason: string
    checks?: SignalChecks
    checks_passed?: number
    checks_required?: number
    rsi?: number
    atr?: number
    ema9?: number
    ema21?: number
    close?: number
    candle_epoch?: number
  }
  execution_timeframe?: string
  signal_timeframe?: string
}

export type TimeframeSignal = PrecisionSignal

export interface PrecisionResponse {
  platform: string
  symbol: string
  engine: string
  mode: string
  timestamp: number
  signal: PrecisionSignal
  signals: Record<string, TimeframeSignal>
  context: Record<string, TimeframeContext>
  signal_timeframe: string
  execution_confirmation_timeframe: string
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

export function getAuthToken(): string | null {
  return localStorage.getItem('revai_access_token')
}

export function authHeaders(): HeadersInit {
  const token = getAuthToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function authFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const response = await fetch(input, {
    ...init,
    headers: { ...authHeaders(), ...(init.headers || {}) },
  })
  if (response.status === 401) {
    localStorage.removeItem('revai_access_token')
    window.dispatchEvent(new Event('revai:unauthorized'))
  }
  return response
}

export async function fetchPrecisionSignal(): Promise<PrecisionResponse> {
  const response = await authFetch(`${REVAI_API}/api/signals/precision`)
  if (!response.ok) {
    throw new Error(`RevAI API error: HTTP ${response.status}`)
  }
  return response.json()
}
