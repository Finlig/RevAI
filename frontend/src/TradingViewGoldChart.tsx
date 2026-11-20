import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ColorType,
  CandlestickSeries,
  createChart,
  createSeriesMarkers,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import { type PrecisionSignal } from './revai'

type Timeframe = '5M' | '15M' | '1H' | '4H' | '1D'
type Candle = { epoch: number; open: number; high: number; low: number; close: number }
type Props = { apiBase: string; signal?: PrecisionSignal; theme?: 'dark' | 'light' }
type OverlayState = { ema: boolean; bollinger: boolean; levels: boolean; patterns: boolean }

const TIMEFRAMES: Timeframe[] = ['5M', '15M', '1H', '4H', '1D']

function ema(values: number[], period: number) {
  const multiplier = 2 / (period + 1)
  let previous = values[0]
  return values.map((value, index) => {
    previous = index === 0 ? value : value * multiplier + previous * (1 - multiplier)
    return previous
  })
}

function bollinger(values: number[], period = 20, deviation = 2) {
  return values.map((_, index) => {
    if (index < period - 1) return null
    const slice = values.slice(index - period + 1, index + 1)
    const mean = slice.reduce((sum, value) => sum + value, 0) / period
    const variance = slice.reduce((sum, value) => sum + (value - mean) ** 2, 0) / period
    const width = Math.sqrt(variance) * deviation
    return { middle: mean, upper: mean + width, lower: mean - width }
  })
}

function price(value?: number) {
  return value == null || !Number.isFinite(value)
    ? '—'
    : value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export default function TradingViewGoldChart({ apiBase, signal, theme = 'dark' }: Props) {
  const hostRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const markerApiRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null)
  const [timeframe, setTimeframe] = useState<Timeframe>('15M')
  const [candles, setCandles] = useState<Candle[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)
  const [overlays, setOverlays] = useState<OverlayState>({
    ema: true, bollinger: true, levels: true, patterns: true,
  })

  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const response = await fetch(`${apiBase.replace(/\/$/, '')}/api/market/gold/${timeframe}`)
        if (!response.ok) throw new Error(`Market feed returned HTTP ${response.status}`)
        const payload = await response.json()
        const rows: Candle[] = (payload.candles ?? []).filter((c: Candle) =>
          Number.isFinite(c.epoch) && Number.isFinite(c.open) &&
          Number.isFinite(c.high) && Number.isFinite(c.low) && Number.isFinite(c.close)
        ).sort((a: Candle, b: Candle) => a.epoch - b.epoch)
        if (!rows.length) throw new Error('No valid Gold candles were returned.')
        if (active) {
          setCandles(rows)
          setUpdatedAt(new Date())
          setError('')
          setLoading(false)
        }
      } catch (cause) {
        if (active) {
          setError(cause instanceof Error ? cause.message : 'Unable to load Gold candles.')
          setLoading(false)
        }
      }
    }
    setLoading(true)
    void load()
    const timer = window.setInterval(() => void load(), 30000)
    return () => { active = false; window.clearInterval(timer) }
  }, [apiBase, timeframe])

  const indicators = useMemo(() => {
    const closes = candles.map(c => c.close)
    return { ema9: ema(closes, 9), ema21: ema(closes, 21), bands: bollinger(closes) }
  }, [candles])

  useEffect(() => {
    if (!hostRef.current) return
    const host = hostRef.current
    const chart = createChart(host, {
      width: host.clientWidth || 800,
      height: 440,
      layout: {
        background: { type: ColorType.Solid, color: theme === 'light' ? '#ffffff' : '#11110f' },
        textColor: theme === 'light' ? '#68645b' : '#aaa392',
        fontFamily: 'Poppins, sans-serif',
      },
      grid: {
        vertLines: { color: theme === 'light' ? '#ece9e2' : '#25241f' },
        horzLines: { color: theme === 'light' ? '#ece9e2' : '#25241f' },
      },
      rightPriceScale: { borderColor: theme === 'light' ? '#dedad1' : '#39362d' },
      timeScale: { borderColor: theme === 'light' ? '#dedad1' : '#39362d', timeVisible: true, secondsVisible: false },
      crosshair: { vertLine: { color: '#8b7440', labelBackgroundColor: '#8b7440' }, horzLine: { color: '#8b7440', labelBackgroundColor: '#8b7440' } },
      handleScroll: true,
      handleScale: true,
    })
    chartRef.current = chart
    const candlesSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#28bd83',
      downColor: '#e66c6c',
      borderVisible: false,
      wickUpColor: '#28bd83',
      wickDownColor: '#e66c6c',
    })
    candleSeriesRef.current = candlesSeries
    markerApiRef.current = createSeriesMarkers(candlesSeries, [] as SeriesMarker<Time>[])

    const resize = new ResizeObserver(entries => {
      const width = entries[0]?.contentRect.width
      if (width) chart.applyOptions({ width })
    })
    resize.observe(host)

    return () => {
      resize.disconnect()
      chart.remove()
      chartRef.current = null
      candleSeriesRef.current = null
      markerApiRef.current = null
    }
  }, [theme])

  useEffect(() => {
    const chart = chartRef.current
    const main = candleSeriesRef.current
    if (!chart || !main || !candles.length) return

    const rows = candles.slice(-250)
    const data = rows.map(c => ({
      time: Math.floor(c.epoch) as UTCTimestamp,
      open: c.open, high: c.high, low: c.low, close: c.close,
    }))
    main.setData(data)

    // Remove and recreate indicator series so each toggle reflects the current candle set.
    const lineSeries: ISeriesApi<'Line'>[] = []
    const priceLines: Array<ReturnType<typeof main.createPriceLine>> = []
    const addLine = (values: Array<number | null>, color: string, title: string, width = 1) => {
      const series = chart.addSeries(LineSeries, {
        color, lineWidth: width as 1 | 2 | 3 | 4,
        priceLineVisible: false, lastValueVisible: false, title,
      })
      series.setData(rows.map((c, i) => values[i] == null ? null : ({
        time: Math.floor(c.epoch) as UTCTimestamp,
        value: values[i] as number,
      })).filter((point): point is { time: UTCTimestamp; value: number } => point !== null))
      lineSeries.push(series)
    }

    const offset = candles.length - rows.length
    if (overlays.ema) {
      addLine(indicators.ema9.slice(offset), '#e7c66d', 'EMA 9', 2)
      addLine(indicators.ema21.slice(offset), '#65a9ed', 'EMA 21', 2)
    }
    if (overlays.bollinger) {
      const selectedBands = indicators.bands.slice(offset)
      addLine(selectedBands.map(v => v?.upper ?? null), '#9b8acb', 'BB Upper')
      addLine(selectedBands.map(v => v?.middle ?? null), '#776b9e', 'BB Middle')
      addLine(selectedBands.map(v => v?.lower ?? null), '#9b8acb', 'BB Lower')
    }

    if (overlays.levels && rows.length > 10) {
      const lookback = rows.slice(-60, -1)
      const resistance = Math.max(...lookback.map(c => c.high))
      const support = Math.min(...lookback.map(c => c.low))
      priceLines.push(main.createPriceLine({ price: resistance, color: '#d49b62', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'Resistance' }))
      priceLines.push(main.createPriceLine({ price: support, color: '#65a98a', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'Support' }))
    }

    const activeSignal = signal?.signal === 'BUY' || signal?.signal === 'SELL' ? signal : undefined
    if (activeSignal) {
      const levels: Array<[number | undefined, string, string]> = [
        [activeSignal.entry, '#e7c66d', 'ENTRY'],
        [activeSignal.stop_loss, '#e66c6c', 'STOP'],
        [activeSignal.tp1, '#28bd83', 'TP1'],
        [activeSignal.tp2, '#28bd83', 'TP2'],
        [activeSignal.tp3, '#28bd83', 'TP3'],
      ]
      levels.forEach(([value, color, title]) => {
        if (value != null && Number.isFinite(value)) {
          priceLines.push(main.createPriceLine({
            price: value, color, lineWidth: 1, lineStyle: 2,
            axisLabelVisible: true, title,
          }))
        }
      })
    }

    if (overlays.patterns) {
      const markers: SeriesMarker<Time>[] = []
      rows.forEach((c, index) => {
        if (index < 1) return
        const previous = rows[index - 1]
        const body = Math.abs(c.close - c.open)
        const range = Math.max(c.high - c.low, 0.000001)
        const lowerWick = Math.min(c.open, c.close) - c.low
        const upperWick = c.high - Math.max(c.open, c.close)
        const bullishEngulf = c.close > c.open && previous.close < previous.open && c.close >= previous.open && c.open <= previous.close
        const bearishEngulf = c.close < c.open && previous.close > previous.open && c.open >= previous.close && c.close <= previous.open
        if (bullishEngulf || (lowerWick > body * 2 && lowerWick / range > 0.5)) {
          markers.push({ time: Math.floor(c.epoch) as UTCTimestamp, position: 'belowBar', color: '#28bd83', shape: 'arrowUp', text: bullishEngulf ? 'Bull engulf' : 'Bull rejection' })
        } else if (bearishEngulf || (upperWick > body * 2 && upperWick / range > 0.5)) {
          markers.push({ time: Math.floor(c.epoch) as UTCTimestamp, position: 'aboveBar', color: '#e66c6c', shape: 'arrowDown', text: bearishEngulf ? 'Bear engulf' : 'Bear rejection' })
        }
      })
      markerApiRef.current?.setMarkers(markers)
    } else {
      markerApiRef.current?.setMarkers([])
    }

    chart.timeScale().fitContent()
    return () => {
      // The chart's own effect may already have disposed it during unmount.
      // Only remove child objects while this chart is still the active instance.
      if (chartRef.current !== chart) return

      try {
        markerApiRef.current?.setMarkers([])
      } catch (error) {
        console.warn('TradingView marker cleanup:', error)
      }

      lineSeries.forEach(series => {
        try {
          chart.removeSeries(series)
        } catch (error) {
          console.warn('TradingView series cleanup:', error)
        }
      })

      priceLines.forEach(line => {
        try {
          main.removePriceLine(line)
        } catch (error) {
          console.warn('TradingView price-line cleanup:', error)
        }
      })
    }
  }, [candles, indicators, overlays, signal, theme])

  const latest = candles[candles.length - 1]
  const toggle = (key: keyof OverlayState) =>
    setOverlays(current => ({ ...current, [key]: !current[key] }))

  return (
    <section className="overview-panel tv-gold-workspace">
      <div className="overview-panel-heading">
        <div>
          <h2>TradingView Chart Workspace</h2>
          <p>XAU/USD · Interactive chart powered by TradingView Lightweight Charts</p>
        </div>
        <span className={`gold-chart-status ${error ? 'stale' : ''}`}><i />{error ? 'FEED ISSUE' : 'DERIV FEED'}</span>
      </div>

      <div className="tv-workspace-toolbar">
        <div className="gold-chart-instrument">
          <span className="gold-chart-symbol">XAU</span>
          <div><strong>Gold / US Dollar</strong><small>{timeframe} · 30-second refresh</small></div>
        </div>
        <div className="gold-timeframe-controls">
          {TIMEFRAMES.map(tf => <button key={tf} type="button" className={timeframe === tf ? 'selected' : ''} onClick={() => setTimeframe(tf)}>{tf}</button>)}
        </div>
      </div>

      <div className="tv-workspace-meta">
        <div><span>LAST PRICE</span><strong>{price(latest?.close)}</strong></div>
        <div><span>REVAI SETUP</span><strong className={signal?.signal === 'BUY' ? 'tv-buy' : signal?.signal === 'SELL' ? 'tv-sell' : ''}>{signal?.signal ?? 'WAIT'}</strong></div>
        <div><span>ENTRY</span><strong>{price(signal?.entry)}</strong></div>
        <div><span>STOP LOSS</span><strong>{price(signal?.stop_loss)}</strong></div>
      </div>

      <div className="tv-overlay-controls">
        {([
          ['ema', 'EMA 9 / 21'],
          ['bollinger', 'Bollinger Bands'],
          ['levels', 'Support / Resistance'],
          ['patterns', 'Reversal markers'],
        ] as Array<[keyof OverlayState, string]>).map(([key, label]) => (
          <button key={key} type="button" className={overlays[key] ? 'active' : ''} onClick={() => toggle(key)}>
            <span />{label}
          </button>
        ))}
      </div>

      <div className="tv-chart-frame">
        <div ref={hostRef} className="tv-chart-host" aria-label={`Interactive XAU/USD ${timeframe} chart`} />
        {loading && !candles.length && <div className="tv-chart-overlay"><span className="gold-chart-spinner" />Loading Gold candles…</div>}
        {error && !candles.length && !loading && <div className="tv-chart-overlay">{error}</div>}
      </div>

      <div className="tv-chart-legend">
        <span><i className="tv-ema9" /> EMA 9</span>
        <span><i className="tv-ema21" /> EMA 21</span>
        <span><i className="tv-bb" /> Bollinger Bands</span>
        <span><i className="tv-entry" /> Entry / SL / TP</span>
      </div>
      <div className="gold-chart-footer">
        <span>Scroll to zoom · Drag to pan · Crosshair for candle values</span>
        <span>{updatedAt ? `Updated ${updatedAt.toLocaleTimeString()}` : 'Waiting for market data'}</span>
      </div>
      {error && candles.length > 0 && <p className="gold-chart-error">{error} Showing the last successful candle data.</p>}
      <p className="tv-chart-disclaimer">Chart overlays are visual analysis aids. Reversal markers use basic candle rules and are not independent trade signals.</p>
    </section>
  )
}
