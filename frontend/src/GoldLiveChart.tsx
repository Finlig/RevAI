import { useEffect, useMemo, useState } from 'react'
import { authFetch } from './revai'

type Timeframe = '5M' | '15M' | '1H' | '4H' | '1D'

type Candle = {
  epoch: number
  open: number
  high: number
  low: number
  close: number
}

type MarketResponse = {
  symbol?: string
  timeframe?: string
  received?: number
  candles?: Candle[]
}

const timeframes: Timeframe[] = ['5M', '15M', '1H', '4H', '1D']

function price(value: number) {
  return value.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

function GoldLiveChart({ apiBase }: { apiBase: string }) {
  const [timeframe, setTimeframe] = useState<Timeframe>('5M')
  const [candles, setCandles] = useState<Candle[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)

  useEffect(() => {
    let active = true
    const base = apiBase.replace(/\/$/, '')

    const loadCandles = async () => {
      try {
        const response = await authFetch(`${base}/api/market/gold/${timeframe}`)
        if (!response.ok) {
          throw new Error(`Market feed returned HTTP ${response.status}`)
        }

        const result: MarketResponse = await response.json()
        const validCandles = (result.candles ?? []).filter((candle) =>
          Number.isFinite(candle.epoch) &&
          Number.isFinite(candle.open) &&
          Number.isFinite(candle.high) &&
          Number.isFinite(candle.low) &&
          Number.isFinite(candle.close)
        )

        if (!validCandles.length) {
          throw new Error('No valid Gold candles were returned by the feed.')
        }

        if (active) {
          setCandles(validCandles)
          setLastUpdated(new Date())
          setError('')
          setLoading(false)
        }
      } catch (err) {
        if (active) {
          setError(err instanceof Error ? err.message : 'Unable to load Gold market data.')
          setLoading(false)
        }
      }
    }

    setLoading(true)
    loadCandles()
    const interval = window.setInterval(loadCandles, 30000)

    return () => {
      active = false
      window.clearInterval(interval)
    }
  }, [apiBase, timeframe])

  const visibleCandles = useMemo(() => candles.slice(-80), [candles])

  const chart = useMemo(() => {
    if (!visibleCandles.length) return null

    const width = 1000
    const height = 410
    const left = 20
    const right = 875
    const top = 24
    const bottom = 340
    const highs = visibleCandles.map(c => c.high)
    const lows = visibleCandles.map(c => c.low)
    const rawMax = Math.max(...highs)
    const rawMin = Math.min(...lows)
    const padding = Math.max((rawMax - rawMin) * 0.08, rawMax * 0.0001)
    const max = rawMax + padding
    const min = rawMin - padding
    const range = max - min || 1
    const y = (value: number) => bottom - ((value - min) / range) * (bottom - top)
    const slot = (right - left) / visibleCandles.length
    const bodyWidth = Math.max(3, Math.min(10, slot * 0.65))

    return {
      width, height, left, right, top, bottom, min, max, y, slot, bodyWidth,
    }
  }, [visibleCandles])

  const latest = visibleCandles[visibleCandles.length - 1]
  const previous = visibleCandles[visibleCandles.length - 2]
  const change = latest && previous ? latest.close - previous.close : 0
  const changePercent = previous?.close ? (change / previous.close) * 100 : 0

  return (
    <section className="overview-panel gold-live-chart">
      <div className="overview-panel-heading gold-chart-heading">
        <div>
          <h2>Live Gold Chart</h2>
          <p>XAU/USD · Deriv market candle feed</p>
        </div>
        <span className={`gold-chart-status ${error ? 'stale' : ''}`}>
          <i />
          {error ? 'FEED ISSUE' : 'LIVE FEED'}
        </span>
      </div>

      <div className="gold-chart-toolbar">
        <div className="gold-chart-instrument">
          <span className="gold-chart-symbol">XAU</span>
          <div>
            <strong>Gold / US Dollar</strong>
            <small>{timeframe} timeframe</small>
          </div>
        </div>
        <div className="gold-timeframe-controls">
          {timeframes.map(tf => (
            <button
              key={tf}
              type="button"
              className={timeframe === tf ? 'selected' : ''}
              onClick={() => setTimeframe(tf)}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>

      <div className="gold-chart-price-row">
        <div>
          <span>LAST CANDLE CLOSE</span>
          <strong>{latest ? price(latest.close) : '—'}</strong>
        </div>
        {latest && previous && (
          <div className={`gold-chart-change ${change >= 0 ? 'up' : 'down'}`}>
            <strong>{change >= 0 ? '+' : ''}{price(change)}</strong>
            <span>{changePercent >= 0 ? '+' : ''}{changePercent.toFixed(2)}%</span>
          </div>
        )}
      </div>

      {loading && !candles.length ? (
        <div className="gold-chart-message" role="status" aria-label="Loading chart"><span className="gold-chart-spinner" /></div>
      ) : chart ? (
        <div className="gold-chart-canvas">
          <svg
            viewBox={`0 0 ${chart.width} ${chart.height}`}
            role="img"
            aria-label={`XAU/USD ${timeframe} candlestick chart`}
            preserveAspectRatio="none"
          >
            {Array.from({ length: 6 }, (_, index) => {
              const value = chart.max - ((chart.max - chart.min) * index / 5)
              const y = chart.y(value)
              return (
                <g key={index}>
                  <line x1={chart.left} x2={chart.right} y1={y} y2={y} className="gold-chart-gridline" />
                  <text x="890" y={y + 4} className="gold-chart-axis-label">{price(value)}</text>
                </g>
              )
            })}

            {visibleCandles.map((candle, index) => {
              const x = chart.left + index * chart.slot + chart.slot / 2
              const bullish = candle.close >= candle.open
              const candleY = chart.y(Math.max(candle.open, candle.close))
              const bodyHeight = Math.max(1.5, Math.abs(chart.y(candle.open) - chart.y(candle.close)))
              const candleClass = bullish ? 'bullish' : 'bearish'

              return (
                <g key={`${candle.epoch}-${index}`} className={`gold-candle ${candleClass}`}>
                  <line
                    x1={x} x2={x}
                    y1={chart.y(candle.high)}
                    y2={chart.y(candle.low)}
                    className="gold-candle-wick"
                  />
                  <rect
                    x={x - chart.bodyWidth / 2}
                    y={candleY}
                    width={chart.bodyWidth}
                    height={bodyHeight}
                    rx="1"
                    className="gold-candle-body"
                  />
                </g>
              )
            })}

            {latest && (
              <>
                <line
                  x1={chart.left}
                  x2={chart.right}
                  y1={chart.y(latest.close)}
                  y2={chart.y(latest.close)}
                  className="gold-chart-last-price"
                />
                <rect
                  x="880"
                  y={chart.y(latest.close) - 11}
                  width="112"
                  height="22"
                  rx="3"
                  className="gold-chart-price-tag"
                />
                <text
                  x="936"
                  y={chart.y(latest.close) + 4}
                  textAnchor="middle"
                  className="gold-chart-price-tag-text"
                >
                  {price(latest.close)}
                </text>
              </>
            )}
          </svg>
        </div>
      ) : (
        <div className="gold-chart-message">No candle data is currently available.</div>
      )}

      <div className="gold-chart-footer">
        <div className="gold-chart-legend">
          <span><i className="bullish-dot" /> Bullish</span>
          <span><i className="bearish-dot" /> Bearish</span>
        </div>
        <span>
          {lastUpdated
            ? `Updated ${lastUpdated.toLocaleTimeString()} · Refreshes every 30s`
            : 'Waiting for market data'}
        </span>
      </div>
      {error && (
        <p className="gold-chart-error">
          {error} {candles.length ? 'Showing the last successfully received candles.' : ''}
        </p>
      )}
    </section>
  )
}

export default GoldLiveChart
