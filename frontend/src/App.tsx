import { useEffect, useState } from 'react'
import { REVAI_API, fetchPrecisionSignal, type PrecisionResponse } from './revai'
import GoldLiveChart from './GoldLiveChart'
import {
  Activity, BarChart3, Bell, CandlestickChart, ChevronDown,
  ChevronRight, CircleHelp, Clock3, Crosshair, Gauge,
  LayoutDashboard, LockKeyhole, Radio,
  Settings, ShieldCheck, UserRound, Wallet,
  Zap
} from 'lucide-react'
import './index.css'

const timeframes = ['1D', '4H', '1H', '15M', '5M'] as const

const navigation = [
  { name: 'Overview', icon: LayoutDashboard },
  { name: 'Analysis', icon: CandlestickChart },
  { name: 'Signals', icon: Radio },
  { name: 'History', icon: Clock3 },
  { name: 'Settings', icon: Settings },
]

function App() {
  const [activeNav, setActiveNav] = useState('Overview')
  const [settingsTab, setSettingsTab] = useState('Profile')
  const [notice, setNotice] = useState('')
  const [marketData, setMarketData] = useState<PrecisionResponse | null>(null)
  const [apiError, setApiError] = useState('')
  const [loading, setLoading] = useState(true)
  const [historyRecords, setHistoryRecords] = useState<any[]>([])
  const [historySummary, setHistorySummary] = useState<any>({})
  const [historyLoading, setHistoryLoading] = useState(false)


  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout>

    const refresh = async () => {
      try {
        const result = await fetchPrecisionSignal()
        if (active) {
          setMarketData(result)
          try {
            const historyResponse = await fetch(`${REVAI_API}/api/signals/history`)
            if (historyResponse.ok) {
              const history = await historyResponse.json()
              setHistoryRecords(history.records ?? [])
              setHistorySummary(history.summary ?? {})
            }
          } catch (historyError) {
            console.error('Unable to refresh signal history:', historyError)
          }
          setApiError('')
        }
      } catch (error) {
        if (active) {
          setApiError(error instanceof Error ? error.message : 'Unable to reach RevAI API')
        }
      } finally {
        if (active) {
          setLoading(false)
          timer = setTimeout(refresh, 60000)
        }
      }
    }

    refresh()

    return () => {
      active = false
      clearTimeout(timer)
    }
  }, [])

  const timeframeSignals = marketData?.signals ?? {}
  const formatPrice = (value?: number) =>
    value === undefined ? '—' : value.toFixed(2)
  const formatMetric = (value?: number) =>
    value === undefined ? '—' : value.toFixed(2)

  const notify = (message: string) => {
    setNotice(message)
    window.setTimeout(() => setNotice(''), 2500)
  }


  const renderSettings = () => (
    <div className="settings-layout">
      <div className="settings-menu">
        {[
          { name: 'Profile', icon: UserRound },
          { name: 'Password', icon: LockKeyhole },
          { name: 'Upgrade Plan', icon: Wallet },
        ].map(item => {
          const Icon = item.icon
          return (
            <button
              key={item.name}
              className={`settings-tab ${settingsTab === item.name ? 'selected' : ''}`}
              onClick={() => setSettingsTab(item.name)}
            >
              <Icon size={18} />
              {item.name}
              <ChevronRight size={15} />
            </button>
          )
        })}
      </div>

      <div className="settings-content">
        {settingsTab === 'Profile' && (
          <>
            <div className="settings-heading">
              <h2>Profile information</h2>
              <p>Manage your personal account details.</p>
            </div>
            <div className="profile-preview">
              <div className="profile-large">R</div>
              <div><strong>RevAI Trader</strong><p>Pro workspace</p></div>
            </div>
            <label>Full name<input defaultValue="RevAI Trader" /></label>
            <label>Email address<input type="email" placeholder="Enter your email address" /></label>
            <label>Phone number<input type="tel" placeholder="Enter phone number" /></label>
            <button className="gold-button" onClick={() => notify('Profile saving will be enabled after backend integration.')}>Save changes</button>
          </>
        )}

        {settingsTab === 'Password' && (
          <>
            <div className="settings-heading">
              <h2>Change password</h2>
              <p>Keep your RevAI account secure.</p>
            </div>
            <label>Current password<input type="password" placeholder="Enter current password" /></label>
            <label>New password<input type="password" placeholder="Enter new password" /></label>
            <label>Confirm new password<input type="password" placeholder="Confirm new password" /></label>
            <button className="gold-button" onClick={() => notify('Password updates will be enabled after authentication is connected.')}>Update password</button>
            <div className="security-note"><ShieldCheck size={17} /> Your account security matters. Never share your password.</div>
          </>
        )}

        {settingsTab === 'Upgrade Plan' && (
          <>
            <div className="settings-heading">
              <h2>Your subscription</h2>
              <p>Choose the RevAI experience that works for you.</p>
            </div>
            <div className="current-plan">
              <div><span>CURRENT WORKSPACE</span><h3>RevAI Pro</h3><p>Premium market intelligence</p></div>
              <Zap size={25} />
            </div>
            <div className="upgrade-feature"><ShieldCheck size={17} /><span>Multi-timeframe Gold analysis</span></div>
            <div className="upgrade-feature"><Radio size={17} /><span>Live trading signals</span></div>
            <div className="upgrade-feature"><BarChart3 size={17} /><span>Signal history and performance</span></div>
            <button className="gold-button" onClick={() => notify('Billing and subscription management will be connected soon.')}>Manage subscription</button>
          </>
        )}
      </div>
    </div>
  )

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><Activity size={22} /></div>
          <div><span className="brand-name">REV<span>AI</span></span><small>GOLD INTELLIGENCE</small></div>
        </div>

        <div className="workspace-label">WORKSPACE</div>
        <nav>
          {navigation.map(item => {
            const Icon = item.icon
            return (
              <button
                key={item.name}
                className={`nav-item ${activeNav === item.name ? 'active' : ''}`}
                onClick={() => setActiveNav(item.name)}
              >
                <Icon size={18} /><span>{item.name}</span>
                {activeNav === item.name && <span className="active-dot" />}
              </button>
            )
          })}
        </nav>

        <div className="sidebar-bottom">
          <div className="plan-card">
            <div className="plan-icon"><Zap size={17} /></div>
            <strong>RevAI Pro</strong>
            <p>Advanced gold market intelligence.</p>
            <button onClick={() => { setActiveNav('Settings'); setSettingsTab('Upgrade Plan') }}>Manage plan <ChevronRight size={14} /></button>
          </div>
          <div className="profile">
            <div className="avatar">R</div>
            <div><strong>RevAI Trader</strong><small>Pro workspace</small></div>
            <ChevronDown size={16} />
          </div>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div className="breadcrumb">Workspace <ChevronRight size={14} /> <strong>{activeNav}</strong></div>
          <div className="top-actions">
            <div className="market-status"><span className={`status-dot ${marketData ? "" : "muted"}`} /> Market feed <span>{apiError ? "Connection error" : loading ? "Connecting..." : "Connected"}</span></div>
            <button className="icon-button" aria-label="Notifications"><Bell size={18} /></button>
            <button className="icon-button" aria-label="Help"><CircleHelp size={18} /></button>
            <div className="top-avatar">R</div>
          </div>
        </header>

        <div className="page">
          {activeNav === 'Settings' ? (
            <>
              <section className="welcome-row">
                <div><div className="eyebrow"><span className="gold-line" /> ACCOUNT CONTROL</div><h1>Settings</h1><p className="subtitle">Manage your profile, security and subscription.</p></div>
              </section>
              {renderSettings()}
            </>
          ) : activeNav === 'Analysis' ? (
            <>
              <section className="welcome-row">
                <div>
                  <div className="eyebrow"><span className="gold-line" /> GOLD MARKET INTELLIGENCE</div>
                  <h1>Market Analysis</h1>
                  <p className="subtitle">Understand why each Gold timeframe is buying, selling or waiting.</p>
                </div>
                <button className="date-button"><Clock3 size={16} /> Live market analysis</button>
              </section>

              <section className="market-banner">
                <div className="gold-symbol">Au</div>
                <div className="instrument">
                  <div className="instrument-title">GOLD <span className="symbol-tag">XAU/USD</span></div>
                  <div className="instrument-sub">Gold / US Dollar <span className="separator">•</span> Independent timeframe analysis</div>
                </div>
                <div className="feed-state">
                  <span className={`status-dot ${marketData ? "" : "muted"}`} />
                  {apiError || (marketData ? "Technical feed connected" : "Awaiting market data")}
                </div>
                <div className="banner-divider" />
                <div className="banner-meta"><small>TIMEFRAMES</small><strong>5</strong></div>
                <div className="banner-meta"><small>ACTIVE SIGNALS</small><strong>{timeframes.filter(tf => ["BUY", "SELL"].includes(timeframeSignals[tf]?.signal)).length}</strong></div>
              </section>

              <section className="metrics-grid">
                <div className="metric-card">
                  <div className="metric-top"><span>Current market price</span><Activity size={17} /></div>
                  <div className="metric-value">{formatPrice(timeframeSignals["5M"]?.analysis?.latest_close ?? timeframeSignals["15M"]?.analysis?.latest_close)} <small>USD</small></div>
                  <div className="metric-foot">Latest completed candle available</div>
                </div>
                <div className="metric-card">
                  <div className="metric-top"><span>BUY signals</span><Gauge size={17} /></div>
                  <div className="metric-value">{timeframes.filter(tf => timeframeSignals[tf]?.signal === "BUY").length}</div>
                  <div className="metric-foot">Independent bullish timeframe readings</div>
                </div>
                <div className="metric-card">
                  <div className="metric-top"><span>SELL signals</span><Crosshair size={17} /></div>
                  <div className="metric-value">{timeframes.filter(tf => timeframeSignals[tf]?.signal === "SELL").length}</div>
                  <div className="metric-foot">Independent bearish timeframe readings</div>
                </div>
                <div className="metric-card">
                  <div className="metric-top"><span>5M volatility</span><Activity size={17} /></div>
                  <div className="metric-value">{formatMetric(timeframeSignals["5M"]?.analysis?.atr)} <small>ATR</small></div>
                  <div className="metric-foot">Average true range on 5-minute candles</div>
                </div>
              </section>

              <section className="section-heading">
                <div><h2>Why the market is moving</h2><p>Actual indicator checks used by the RevAI signal engine</p></div>
                <div className="scanner-status"><span className={`status-dot ${marketData ? "" : "muted"}`} /> {marketData ? "Diagnostics connected" : "Waiting for feed"}</div>
              </section>

              <section className="signal-cards-section">
                {timeframes.map(tf => {
                  const item = timeframeSignals[tf]
                  const details = item?.analysis
                  const direction = item?.signal ?? "WAIT"
                  const checks = direction === "SELL" ? details?.sell_checks : details?.buy_checks
                  const reasons = direction === "SELL" ? details?.sell_reasons : details?.buy_reasons

                  return (
                    <article className="signal-card" key={tf}>
                      <div className="signal-card-header">
                        <div>
                          <span className="signal-timeframe">{tf}</span>
                          <span className="signal-type">INDEPENDENT TIMEFRAME</span>
                        </div>
                        <span className="signal-wait">{direction}</span>
                      </div>

                      <div className="signal-card-body">
                        <div className="signal-direction">{direction === "BUY" ? "Bullish direction" : direction === "SELL" ? "Bearish direction" : "No qualified direction"}</div>
                        <p>{item?.reason ?? "Waiting for timeframe data."}</p>
                        <div className="signal-quick-metrics">
                          <div><span>Gold price</span><strong>{formatPrice(details?.latest_close)}</strong></div>
                          <div><span>RSI</span><strong>{formatMetric(details?.rsi)}</strong></div>
                        </div>
                      </div>

                      <details className="signal-technical-details">
                        <summary>View technical details and checks</summary>
                      <div className="signal-card-details">
                        <div><span>EMA 9</span><strong>{formatPrice(details?.ema9)}</strong></div>
                        <div><span>EMA 21</span><strong>{formatPrice(details?.ema21)}</strong></div>
                        <div><span>RSI</span><strong>{formatMetric(details?.rsi)}</strong></div>
                        <div><span>ATR</span><strong>{formatMetric(details?.atr)}</strong></div>
                        <div><span>Latest close</span><strong>{formatPrice(details?.latest_close)}</strong></div>
                        <div><span>Buy score</span><strong>{item?.buy_score ?? "—"}/5</strong></div>
                        <div><span>Sell score</span><strong>{item?.sell_score ?? "—"}/5</strong></div>
                        <div><span>Entry</span><strong>{formatPrice(item?.entry)}</strong></div>
                        <div><span>Stop loss</span><strong>{formatPrice(item?.stop_loss)}</strong></div>
                        <div><span>TP1</span><strong>{formatPrice(item?.tp1)}</strong></div>
                        <div><span>TP2</span><strong>{formatPrice(item?.tp2)}</strong></div>
                        <div><span>TP3</span><strong>{formatPrice(item?.tp3)}</strong></div>
                      </div>

                      {checks && (
                        <div className="content-panel">
                          <div className="panel-heading"><div><h3>{direction} confirmation checks</h3><p>{reasons?.length ?? 0} of 5 conditions passed</p></div><ShieldCheck size={18} /></div>
                          <div className="risk-list">
                            {Object.entries(checks).map(([name, passed]) => (
                              <div key={name}>
                                <span>{name}</span>
                                <strong className={passed ? "gold-text" : ""}>{passed ? "Passed" : "Not passed"}</strong>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {direction === "WAIT" && (
                        <div className="content-panel">
                          <div className="panel-heading"><div><h3>What is preventing a signal?</h3><p>Buy and sell confirmation breakdown</p></div><ShieldCheck size={18} /></div>
                          <div className="risk-list">
                            <div><span>Buy conditions passed</span><strong>{item?.buy_score ?? "—"}/5</strong></div>
                            <div><span>Sell conditions passed</span><strong>{item?.sell_score ?? "—"}/5</strong></div>
                            <div><span>Decision</span><strong>{item?.reason ?? "Awaiting analysis"}</strong></div>
                          </div>
                        </div>
                      )}

                      </details>

                      <div className="signal-card-footer">
                        <span><span className={`status-dot ${details ? "" : "muted"}`} /> {details ? "Technical diagnostics available" : "Detailed diagnostics unavailable"}</span>
                        <span>XAU/USD</span>
                      </div>
                    </article>
                  )
                })}
              </section>

              <section className="lower-grid">
                <div className="content-panel">
                  <div className="panel-heading"><div><h3>News and macro intelligence</h3><p>External market catalysts</p></div><Activity size={18} /></div>
                  <div className="risk-list">
                    <div><span>Economic news feed</span><strong>Not connected yet</strong></div>
                    <div><span>US dollar and Treasury yields</span><strong>Awaiting data integration</strong></div>
                    <div><span>Federal Reserve and inflation events</span><strong>Awaiting data integration</strong></div>
                    <div><span>News impact assessment</span><strong>Not yet available</strong></div>
                  </div>
                </div>
                <div className="content-panel">
                  <div className="panel-heading"><div><h3>Next-day outlook</h3><p>Scenario-based forecast for Gold</p></div><Gauge size={18} /></div>
                  <div className="risk-list">
                    <div><span>Tomorrow's directional bias</span><strong>Not yet calculated</strong></div>
                    <div><span>Expected trading range</span><strong>Not yet calculated</strong></div>
                    <div><span>Bullish and bearish scenarios</span><strong>Awaiting forecast engine</strong></div>
                    <div><span>Forecast confidence</span><strong>Not yet calibrated</strong></div>
                  </div>
                  <p className="metric-foot">RevAI will only publish a forecast when technical and verified news data are available. No direction or price target is being invented.</p>
                </div>
              </section>
            </>
          ) : activeNav === 'History' ? (
            <section className="signal-only-page">
              <div className="history-dashboard">
                <div className="history-heading">
                  <div>
                    <h2>Signal history</h2>
                    <p>Track every generated XAU/USD signal and its outcome</p>
                  </div>
                  <button
                    className="history-refresh"
                    onClick={async () => {
                      setHistoryLoading(true)
                      try {
                        const response = await fetch(`${REVAI_API}/api/signals/history`)
                        if (!response.ok) throw new Error('History request failed')
                        const data = await response.json()
                        setHistoryRecords(data.records ?? [])
                        setHistorySummary(data.summary ?? {})
                      } catch {
                        notify('Unable to refresh signal history')
                      } finally {
                        setHistoryLoading(false)
                      }
                    }}
                  >
                    {historyLoading ? 'REFRESHING...' : 'REFRESH'}
                  </button>
                </div>

                <div className="history-stats">
                  <div className="history-stat"><span>TOTAL SIGNALS</span><strong>{historySummary.total ?? 0}</strong></div>
                  <div className="history-stat"><span>ACTIVE</span><strong>{historySummary.active ?? 0}</strong></div>
                  <div className="history-stat"><span>TP1 HIT</span><strong>{historySummary.tp1 ?? 0}</strong></div>
                  <div className="history-stat"><span>TP2 HIT</span><strong>{historySummary.tp2 ?? 0}</strong></div>
                  <div className="history-stat"><span>TP3 HIT</span><strong>{historySummary.tp3 ?? 0}</strong></div>
                  <div className="history-stat"><span>STOP LOSS</span><strong>{historySummary.stop_loss ?? 0}</strong></div>
                </div>

                <div className="history-table-wrap">
                  <table className="history-table">
                    <thead>
                      <tr>
                        <th>DATE / TIME</th>
                        <th>TIMEFRAME</th>
                        <th>TYPE</th>
                        <th>SIGNAL</th>
                        <th>ENTRY</th>
                        <th>STOP LOSS</th>
                        <th>TP1</th>
                        <th>TP2</th>
                        <th>TP3</th>
                        <th>RESULT</th>
                      </tr>
                    </thead>
                    <tbody>
                      {historyRecords.length ? historyRecords.map((record) => (
                        <tr key={record.signal_key}>
                          <td>{new Date(record.issued_at * 1000).toLocaleString()}</td>
                          <td>{record.timeframe}</td>
                          <td>{record.signal_type}</td>
                          <td><span className={`history-direction ${record.direction.toLowerCase()}`}>{record.direction}</span></td>
                          <td>{formatPrice(record.entry)}</td>
                          <td>{formatPrice(record.stop_loss)}</td>
                          <td>{formatPrice(record.tp1)}</td>
                          <td>{formatPrice(record.tp2)}</td>
                          <td>{formatPrice(record.tp3)}</td>
                          <td><span className={`history-status ${record.status.toLowerCase().replaceAll('_', '-')}`}>{record.status.replaceAll('_', ' ')}</span></td>
                        </tr>
                      )) : (
                        <tr><td colSpan={10} className="history-no-data">
                          No signals recorded yet. Qualified BUY and SELL signals will appear here automatically.
                        </td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          ) : activeNav === 'Signals' ? (
            <section className="signal-only-page">
              {timeframes.some((tf) =>
                ['BUY', 'SELL'].includes(timeframeSignals[tf]?.signal)
              ) ? (
                <div className="timeframe-signal-grid">
                  {timeframes
                    .filter((tf) =>
                      ['BUY', 'SELL'].includes(timeframeSignals[tf]?.signal)
                    )
                    .map((tf) => {
                      const item = timeframeSignals[tf]
                      const isBuy = item.signal === 'BUY'
                      const higherTf = ({ '4H': '1D', '1H': '4H', '15M': '1H', '5M': '15M' } as Record<string, string>)[tf]
                      const higherSignal = higherTf ? timeframeSignals[higherTf]?.signal : undefined
                      const setupType = higherSignal && higherSignal !== item.signal
                        ? 'COUNTERTREND'
                        : ['5M', '15M'].includes(tf) ? 'QUICK SCALP' : 'TREND'
                      const timeframeMs = { '1D': 86400000, '4H': 14400000, '1H': 3600000, '15M': 900000, '5M': 300000 }[tf]
                      const validUntil = new Date((Math.floor(Date.now() / timeframeMs) + 1) * timeframeMs)
                      const confirmationScore = Math.max(item.buy_score ?? 0, item.sell_score ?? 0)

                      return (
                        <article className="qualified-signal-card" key={tf}>
                          <div className="qualified-signal-label">
                            REVAI GOLD SIGNAL · XAU/USD
                          </div>
                          <div className="signal-card-badges">
                            <span className="signal-timeframe-badge">{tf}</span>
                            <span className={`signal-action-badge ${isBuy ? 'buy' : 'sell'}`}>
                              {isBuy ? 'BUY NOW' : 'SELL NOW'}
                            </span>
                            <span className={`signal-setup-badge ${setupType.toLowerCase().replace(' ', '-')}`}>
                              {setupType}
                            </span>
                          </div>
                          <div className={`signal-main-entry ${isBuy ? 'buy' : 'sell'}`}>
                            {formatPrice(item.entry)}
                          </div>
                          <div className="qualified-signal-timeframe">
                            {tf} INDEPENDENT SIGNAL
                          </div>
                          <div className="qualified-signal-levels">
                            <div className="signal-level">
                              <span>ENTRY</span>
                              <strong>{formatPrice(item.entry)}</strong>
                            </div>
                            <div className="signal-level">
                              <span>STOP LOSS</span>
                              <strong>{formatPrice(item.stop_loss)}</strong>
                            </div>
                            {item.tp1 !== undefined && (
                              <div className="signal-level">
                                <span>TP1</span>
                                <strong>{formatPrice(item.tp1)}</strong>
                              </div>
                            )}
                            {item.tp2 !== undefined && (
                              <div className="signal-level">
                                <span>TP2</span>
                                <strong>{formatPrice(item.tp2)}</strong>
                              </div>
                            )}
                            {item.tp3 !== undefined && (
                              <div className="signal-level">
                                <span>TP3</span>
                                <strong>{formatPrice(item.tp3)}</strong>
                              </div>
                            )}
                          </div>
                          <div className="signal-validity">
                            <span>VALID UNTIL</span>
                            <strong>{validUntil.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</strong>
                            <span className="signal-confirmation">
                              {confirmationScore}/5 confirmation checks
                            </span>
                          </div>
                          <button
                            type="button"
                            className="copy-signal-button"
                            onClick={() => {
                              const text = [
                                `REVAI GOLD SIGNAL - XAU/USD`,
                                `${item.signal} | ${tf} | ${setupType}`,
                                `Entry: ${formatPrice(item.entry)}`,
                                `Stop Loss: ${formatPrice(item.stop_loss)}`,
                                `TP1: ${formatPrice(item.tp1)}`,
                                `TP2: ${formatPrice(item.tp2)}`,
                                `TP3: ${formatPrice(item.tp3)}`,
                                `Valid until: ${validUntil.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`,
                                `Confirmation: ${confirmationScore}/5`
                              ].join('\n')
                              navigator.clipboard.writeText(text)
                                .then(() => setNotice('Signal copied to clipboard.'))
                                .catch(() => setNotice('Could not copy signal.'))
                            }}
                          >
                            COPY SIGNAL
                          </button>
                        </article>
                      )
                    })}
                </div>
              ) : (
                <div className="waiting-quality-setup">
                  WAIT — NO ACTIVE SIGNAL
                </div>
              )}
            </section>
          ) : (
            <section className="overview-page">
              <div className="overview-heading">
                <div>

                  <h1>Gold Overview</h1>
                  <p className="subtitle">Live XAU/USD intelligence, signal decisions and execution levels.</p>
                </div>
                <div className={`overview-feed-pill ${apiError ? 'is-error' : loading ? 'is-loading' : 'is-live'}`}>
                  <span className="status-dot" />
                  {apiError ? 'FEED ERROR' : loading ? 'CONNECTING' : 'LIVE DATA'}
                </div>
              </div>

              <div className="overview-market-banner">
                <div className="overview-gold-mark">Au</div>
                <div className="overview-instrument">
                  <span>PRIMARY INSTRUMENT</span>
                  <strong>Gold <small>XAU/USD</small></strong>
                  <p>Gold / US Dollar · Deriv market data</p>
                </div>
                <div className="overview-market-price">
                  <span>LATEST AVAILABLE PRICE</span>
                  <strong>{formatPrice(timeframeSignals['5M']?.analysis?.latest_close ?? timeframeSignals['15M']?.analysis?.latest_close)}</strong>
                  <small>USD · latest completed candle</small>
                </div>
              </div>

              <div className="overview-metrics">
                <article className="overview-metric">
                  <span>ACTIVE TIMEFRAME SIGNALS</span>
                  <strong>{timeframes.filter(tf => ['BUY', 'SELL'].includes(timeframeSignals[tf]?.signal)).length}<small> / 5</small></strong>
                  <p>Qualified BUY or SELL readings</p>
                </article>
                <article className="overview-metric">
                  <span>BUY READINGS</span>
                  <strong className="overview-buy">{timeframes.filter(tf => timeframeSignals[tf]?.signal === 'BUY').length}</strong>
                  <p>Independent bullish timeframes</p>
                </article>
                <article className="overview-metric">
                  <span>SELL READINGS</span>
                  <strong className="overview-sell">{timeframes.filter(tf => timeframeSignals[tf]?.signal === 'SELL').length}</strong>
                  <p>Independent bearish timeframes</p>
                </article>
                <article className="overview-metric">
                  <span>5M VOLATILITY</span>
                  <strong>{formatMetric(timeframeSignals['5M']?.analysis?.atr)}<small> ATR</small></strong>
                  <p>Average true range · 5-minute</p>
                </article>
              </div>

              <div className="overview-main-grid">
                <section className="overview-panel">
                  <div className="overview-panel-heading">
                    <div><h2>Gold Signal Queue</h2><p>Independent timeframe engine · XAU/USD</p></div>
                    <span className="overview-count">5 TIMEFRAMES</span>
                  </div>
                  <div className="overview-queue-list">
                    {timeframes.map(tf => {
                      const item = timeframeSignals[tf]
                      const direction = item?.signal ?? 'WAIT'
                      return (
                        <article className="overview-queue-row" key={tf}>
                          <div className="overview-queue-tf">{tf}</div>
                          <div className="overview-queue-direction">
                            <span className={`overview-direction-tag ${direction.toLowerCase()}`}>{direction}</span>
                            <small>{item?.reason ?? 'Waiting for timeframe data.'}</small>
                          </div>
                          <div className="overview-queue-level">
                            <span>ENTRY</span><strong>{formatPrice(item?.entry)}</strong>
                          </div>
                          <div className="overview-queue-level overview-queue-stop">
                            <span>STOP LOSS</span><strong>{formatPrice(item?.stop_loss)}</strong>
                          </div>
                        </article>
                      )
                    })}
                  </div>
                  <button className="overview-text-action" type="button" onClick={() => setActiveNav('Signals')}>View signal details <ChevronRight size={15} /></button>
                </section>

                <GoldLiveChart apiBase={REVAI_API} />
              </div>

              <section className="overview-panel">
                <div className="overview-panel-heading">
                  <div><h2>Market Data Quality</h2><p>Feed diagnostics reported by the backend</p></div>
                  <Activity size={19} />
                </div>
                {marketData?.data_quality ? (
                  <div className="overview-quality-grid">
                    {Object.entries(marketData.data_quality).map(([tf, quality]) => (
                      <div className="overview-quality-item" key={tf}>
                        <strong>{tf}</strong>
                        <span>{quality.received} / {quality.requested} received</span>
                        <small>{quality.data_quality.valid_received} valid · {quality.data_quality.gap_count} gaps · {quality.data_quality.misaligned_count} misaligned</small>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="overview-quality-empty">{apiError || 'Waiting for backend data-quality diagnostics.'}</p>
                )}
              </section>
              <div className="overview-footer-note">RevAI can make mistakes. Use proper risk management.</div>
            </section>
          )}
          <footer><div className="footer-brand">REV<span>AI</span></div><span>Gold intelligence, disciplined execution.</span><span className="disclaimer">RevAI can make mistakes. Use proper risk management.</span></footer>
        </div>
      </main>

      <nav className="mobile-bottom-nav">
        {navigation.map(item => {
          const Icon = item.icon
          return <button key={item.name} className={activeNav === item.name ? 'active' : ''} onClick={() => setActiveNav(item.name)}><Icon size={20} /><span>{item.name}</span></button>
        })}
      </nav>

      {notice && <div className="toast"><Activity size={15} /> {notice}</div>}
    </div>
  )
}

export default App
