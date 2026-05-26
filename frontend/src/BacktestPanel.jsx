import { useState } from 'react'
import { XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine, Area, AreaChart } from 'recharts'

const API = import.meta.env.DEV ? '/api' : ''

const PRESETS = {
  baseline: {
    label: 'Baseline',
    desc: 'IW Exact: 5% SL, 2x/3x R:R, 5 positions — CAGR +7.7%, PF 1.54',
    cfg: { sl_pct: 0.05, rr_t1: 2.0, rr_t2: 3.0, max_hold_days: 60, risk_per_trade_pct: 0.02,
           max_open_positions: 5, max_per_sector: 2, min_rsi: 0, regime_filter: false,
           min_volume_ratio: 0, avoid_months: '', max_dist_above_52w: 0 },
  },
  momentum: {
    label: 'Momentum Rider',
    desc: 'BEST RETURN: RSI>55, 8 positions, 1.5% risk — CAGR +8.1%, Rs 5L to Rs 7.5L',
    cfg: { sl_pct: 0.05, rr_t1: 2.0, rr_t2: 3.0, max_hold_days: 60, risk_per_trade_pct: 0.015,
           max_open_positions: 8, max_per_sector: 2, min_rsi: 55, regime_filter: false,
           min_volume_ratio: 0, avoid_months: '', max_dist_above_52w: 0 },
  },
  fresh: {
    label: 'Fresh Breakout',
    desc: 'RSI>55 + only fresh breakouts (<3% above 52w) — CAGR +8.0%, lowest DD -13.8%',
    cfg: { sl_pct: 0.05, rr_t1: 2.0, rr_t2: 3.0, max_hold_days: 60, risk_per_trade_pct: 0.015,
           max_open_positions: 8, max_per_sector: 2, min_rsi: 55, regime_filter: false,
           min_volume_ratio: 0, avoid_months: '', max_dist_above_52w: 0.03 },
  },
  low_dd: {
    label: 'Low Drawdown',
    desc: '8% SL + RSI>60 + 10 positions — 53% win rate, only -11% max DD',
    cfg: { sl_pct: 0.08, rr_t1: 2.0, rr_t2: 3.0, max_hold_days: 60, risk_per_trade_pct: 0.01,
           max_open_positions: 10, max_per_sector: 3, min_rsi: 60, regime_filter: false,
           min_volume_ratio: 0, avoid_months: '', max_dist_above_52w: 0, max_sl_pct: 0.10 },
  },
  bull_regime: {
    label: 'Bull Only',
    desc: 'RSI>55 + Nifty>200 DMA — avoids bear markets, reduces 2026 losses',
    cfg: { sl_pct: 0.05, rr_t1: 2.0, rr_t2: 3.0, max_hold_days: 60, risk_per_trade_pct: 0.015,
           max_open_positions: 8, max_per_sector: 2, min_rsi: 55, regime_filter: true,
           min_volume_ratio: 0, avoid_months: '', max_dist_above_52w: 0 },
  },
  seasonal: {
    label: 'Seasonal Smart',
    desc: 'RSI>55 + skip September + fresh breakouts — best risk-adjusted combo',
    cfg: { sl_pct: 0.05, rr_t1: 2.0, rr_t2: 3.0, max_hold_days: 60, risk_per_trade_pct: 0.015,
           max_open_positions: 8, max_per_sector: 2, min_rsi: 55, regime_filter: false,
           min_volume_ratio: 0, avoid_months: '9', max_dist_above_52w: 0.03 },
  },
  aggressive: {
    label: 'Aggressive',
    desc: '8% SL + 90 day hold — wider swings, needs more patience',
    cfg: { sl_pct: 0.08, rr_t1: 2.0, rr_t2: 3.0, max_hold_days: 90, risk_per_trade_pct: 0.02,
           max_open_positions: 5, max_per_sector: 2, min_rsi: 55, regime_filter: false,
           min_volume_ratio: 0, avoid_months: '', max_dist_above_52w: 0, max_sl_pct: 0.10 },
  },
}

const DEFAULT_CFG = {
  initial_capital: 500000,
  risk_per_trade_pct: 0.02,
  sl_pct: 0.05, rr_t1: 2.0, rr_t2: 3.0,
  max_hold_days: 60,
  book_pct_t1: 0.50, sl_to_breakeven: true,
  max_open_positions: 5, max_per_sector: 2,
  cooldown_days: 10, max_sl_pct: 0.08,
  min_rsi: 0,
  regime_filter: false,
  min_volume_ratio: 0,
  avoid_months: '',
  max_dist_above_52w: 0,
}

export default function BacktestPanel() {
  const [cfg, setCfg] = useState(DEFAULT_CFG)
  const [activePreset, setActivePreset] = useState(null)
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [tab, setTab] = useState('stats')
  const [showAdvanced, setShowAdvanced] = useState(false)

  function set(key, val) { setCfg(p => ({ ...p, [key]: val })); setActivePreset(null) }

  function applyPreset(key) {
    const p = PRESETS[key]
    setCfg(prev => ({ ...prev, ...p.cfg }))
    setActivePreset(key)
  }

  async function run() {
    setLoading(true); setError(null)
    try {
      const res = await fetch(`${API}/backtest/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(cfg),
      })
      if (!res.ok) throw new Error(await res.text())
      setResult(await res.json())
      setTab('stats')
    } catch (e) {
      setError(String(e.message || e))
    } finally { setLoading(false) }
  }

  const s = result?.stats
  const trades = result?.trades || []
  const eq = result?.equity_curve || []

  return (
    <div className="card">
      <b style={{ fontSize: 16 }}>52-Week Breakout Portfolio Backtest</b>
      <div className="muted" style={{ marginTop: 4 }}>
        Backtest across {result?.stocks_loaded || '~43'} Nifty 50 stocks with position sizing, sector limits &amp; regime filters
      </div>

      {/* Strategy Presets */}
      <div style={{ marginTop: 14 }}>
        <div className="muted" style={{ marginTop: 0, marginBottom: 8 }}><b>STRATEGY PRESETS</b></div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {Object.entries(PRESETS).map(([key, p]) => (
            <button key={key} onClick={() => applyPreset(key)}
              style={{
                padding: '6px 14px', fontSize: 12, borderRadius: 6, cursor: 'pointer',
                background: activePreset === key ? '#238636' : '#21262d',
                border: `1px solid ${activePreset === key ? '#2ea043' : '#30363d'}`,
                color: activePreset === key ? '#fff' : '#c9d1d9',
                fontWeight: activePreset === key ? 700 : 400,
              }}>
              {p.label}
            </button>
          ))}
        </div>
        {activePreset && (
          <div className="muted" style={{ marginTop: 6, color: '#58a6ff' }}>
            {PRESETS[activePreset].desc}
          </div>
        )}
      </div>

      {/* Config controls */}
      <div className="bt-controls" style={{ marginTop: 12 }}>
        <label>Capital (Rs)
          <input type="number" min="50000" step="50000" value={cfg.initial_capital}
            onChange={e => set('initial_capital', +e.target.value)} disabled={loading} />
        </label>
        <label>Risk/trade %
          <input type="number" min="0.5" max="10" step="0.5"
            value={+(cfg.risk_per_trade_pct * 100).toFixed(1)}
            onChange={e => set('risk_per_trade_pct', +e.target.value / 100)} disabled={loading} />
        </label>
        <label>SL %
          <input type="number" min="1" max="15" step="1"
            value={+(cfg.sl_pct * 100).toFixed(0)}
            onChange={e => set('sl_pct', +e.target.value / 100)} disabled={loading} />
        </label>
        <label>R:R T1
          <input type="number" min="1" max="5" step="0.5" value={cfg.rr_t1}
            onChange={e => set('rr_t1', +e.target.value)} disabled={loading} />
        </label>
        <label>R:R T2
          <input type="number" min="1.5" max="8" step="0.5" value={cfg.rr_t2}
            onChange={e => set('rr_t2', +e.target.value)} disabled={loading} />
        </label>
        <label>Max hold (d)
          <input type="number" min="10" max="250" step="10" value={cfg.max_hold_days}
            onChange={e => set('max_hold_days', +e.target.value)} disabled={loading} />
        </label>
        <label>Max pos
          <input type="number" min="1" max="20" step="1" value={cfg.max_open_positions}
            onChange={e => set('max_open_positions', +e.target.value)} disabled={loading} />
        </label>
        <label>Max/sect
          <input type="number" min="1" max="5" step="1" value={cfg.max_per_sector}
            onChange={e => set('max_per_sector', +e.target.value)} disabled={loading} />
        </label>
        <label>Min RSI
          <input type="number" min="0" max="80" step="5" value={cfg.min_rsi}
            onChange={e => set('min_rsi', +e.target.value)} disabled={loading} />
        </label>
      </div>

      {/* Advanced filters toggle */}
      <div style={{ marginTop: 8 }}>
        <button onClick={() => setShowAdvanced(!showAdvanced)}
          style={{ fontSize: 12, padding: '4px 12px', background: 'transparent', border: '1px solid #30363d', color: '#58a6ff', cursor: 'pointer', borderRadius: 4 }}>
          {showAdvanced ? 'Hide' : 'Show'} Advanced Filters
        </button>
      </div>

      {showAdvanced && (
        <div className="bt-controls" style={{ marginTop: 8, borderColor: '#1f6feb' }}>
          <label style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={cfg.regime_filter}
              onChange={e => set('regime_filter', e.target.checked)} disabled={loading} />
            <span style={{ fontSize: 12, textTransform: 'none', letterSpacing: 0 }}>
              Nifty &gt; 200 DMA only (bull regime)
            </span>
          </label>
          <label>Min vol ratio
            <input type="number" min="0" max="5" step="0.1" value={cfg.min_volume_ratio}
              onChange={e => set('min_volume_ratio', +e.target.value)} disabled={loading}
              style={{ width: 65 }} />
          </label>
          <label>Avoid months
            <input type="text" value={cfg.avoid_months} placeholder="e.g. 2,9"
              onChange={e => set('avoid_months', e.target.value)} disabled={loading}
              style={{ width: 80, background: '#161b22', border: '1px solid #30363d', color: '#e6edf3', borderRadius: 4, padding: '6px 8px', fontSize: 13 }} />
          </label>
          <label>Max dist 52w %
            <input type="number" min="0" max="20" step="1"
              value={+(cfg.max_dist_above_52w * 100).toFixed(0)}
              onChange={e => set('max_dist_above_52w', +e.target.value / 100)} disabled={loading}
              style={{ width: 65 }} />
          </label>
          <label style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={cfg.sl_to_breakeven}
              onChange={e => set('sl_to_breakeven', e.target.checked)} disabled={loading} />
            <span style={{ fontSize: 12, textTransform: 'none', letterSpacing: 0 }}>
              Move SL to breakeven after T1
            </span>
          </label>
        </div>
      )}

      {/* Run button */}
      <div style={{ marginTop: 12 }}>
        <button className="primary" onClick={run} disabled={loading}
          style={{ padding: '10px 28px', fontSize: 14, fontWeight: 700 }}>
          {loading ? 'Running backtest...' : 'Run Backtest'}
        </button>
        {s && !loading && (
          <span className="muted" style={{ marginLeft: 12, marginTop: 0 }}>
            {s.total_trades} trades across {s.stocks_traded} stocks in {s.n_years}y
          </span>
        )}
      </div>

      {error && <div className="explanation" style={{ borderLeftColor: '#f85149', marginTop: 12 }}>{error}</div>}

      {/* Results */}
      {s && (
        <>
          {/* KPI row */}
          <div className="stats-row" style={{ gridTemplateColumns: 'repeat(7, 1fr)', marginTop: 16 }}>
            <Stat label="Trades" value={s.total_trades} />
            <Stat label="Win Rate" value={`${s.win_rate}%`} cls={s.win_rate > 45 ? 'win' : s.win_rate < 35 ? 'loss' : ''} />
            <Stat label="P&L" value={`${(s.total_pnl_abs / 1000).toFixed(0)}K`}
              cls={s.total_pnl_abs > 0 ? 'win' : 'loss'} />
            <Stat label="CAGR" value={`${s.cagr_pct}%`} cls={s.cagr_pct > 0 ? 'win' : 'loss'} />
            <Stat label="Max DD" value={`${s.max_drawdown_pct}%`} cls="loss" />
            <Stat label="Profit Factor" value={s.profit_factor} cls={s.profit_factor > 1.3 ? 'win' : s.profit_factor < 1 ? 'loss' : ''} />
            <Stat label="T1 / T2 Hit" value={`${s.t1_hit_rate}/${s.t2_hit_rate}%`} />
          </div>

          {/* Equity curve */}
          <div style={{ marginTop: 16 }}>
            <div className="muted" style={{ marginTop: 0 }}>
              <b>Equity Curve</b> — Rs {(s.initial_capital / 1000).toFixed(0)}K to Rs {(s.final_equity / 1000).toFixed(0)}K
              ({s.total_return_pct > 0 ? '+' : ''}{s.total_return_pct}% over {s.n_years}y)
            </div>
            <div style={{ width: '100%', height: 260, marginTop: 8 }}>
              <ResponsiveContainer>
                <AreaChart data={eq}>
                  <defs>
                    <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#58a6ff" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#58a6ff" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#30363d" />
                  <XAxis dataKey="date" stroke="#8b949e" tick={{ fontSize: 9 }}
                    tickFormatter={d => d?.slice(0, 7)} interval={Math.max(1, Math.floor(eq.length / 8))} />
                  <YAxis stroke="#8b949e" tick={{ fontSize: 10 }}
                    tickFormatter={v => `${(v / 1000).toFixed(0)}K`} />
                  <Tooltip contentStyle={{ background: '#161b22', border: '1px solid #30363d', fontSize: 12 }}
                    formatter={(v) => [`Rs ${Number(v).toLocaleString()}`, 'Equity']} />
                  <ReferenceLine y={s.initial_capital} stroke="#8b949e" strokeDasharray="5 5" label="" />
                  <Area type="monotone" dataKey="equity" stroke="#58a6ff" fill="url(#eqGrad)" strokeWidth={2} dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Tabs */}
          <div style={{ display: 'flex', gap: 0, marginTop: 18, borderBottom: '1px solid #30363d' }}>
            {['stats', 'trades', 'sectors', 'stocks'].map(t => (
              <button key={t} onClick={() => setTab(t)}
                style={{
                  background: tab === t ? '#21262d' : 'transparent', border: 'none',
                  borderBottom: tab === t ? '2px solid #58a6ff' : '2px solid transparent',
                  color: tab === t ? '#e6edf3' : '#8b949e', padding: '8px 16px',
                  fontSize: 13, cursor: 'pointer', fontWeight: tab === t ? 700 : 400,
                }}>
                {t === 'stats' ? 'Details' : t === 'trades' ? `Trades (${trades.length})` :
                  t === 'sectors' ? 'Sectors' : 'Top Stocks'}
              </button>
            ))}
          </div>

          <div style={{ marginTop: 12 }}>
            {tab === 'stats' && <StatsTab s={s} />}
            {tab === 'trades' && <TradesTab trades={trades} />}
            {tab === 'sectors' && <SectorsTab data={s.by_sector} />}
            {tab === 'stocks' && <StocksTab data={s.by_stock} />}
          </div>
        </>
      )}
    </div>
  )
}

function Stat({ label, value, cls = '' }) {
  return (
    <div className={`stat ${cls}`}>
      <div className="stat-num" style={{ fontSize: 18 }}>{value}</div>
      <div className="stat-lbl">{label}</div>
    </div>
  )
}

function StatsTab({ s }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
      <div>
        <div className="muted" style={{ marginTop: 0, marginBottom: 8 }}><b>Performance</b></div>
        <div className="kv">
          <span>Avg Win</span><b className="win">{s.avg_win_pct}%</b>
          <span>Avg Loss</span><b className="loss">{s.avg_loss_pct}%</b>
          <span>Best Trade</span><b>{s.best_trade_pct}%</b>
          <span>Worst Trade</span><b>{s.worst_trade_pct}%</b>
          <span>Avg P&L / trade</span><b className={s.avg_pnl_pct > 0 ? 'win' : 'loss'}>{s.avg_pnl_pct}%</b>
          <span>Avg Holding</span><b>{s.avg_holding_days} days</b>
          <span>Max Consec Loss</span><b>{s.max_consec_losses}</b>
        </div>

        <div className="muted" style={{ marginTop: 16, marginBottom: 8 }}><b>Exit Reasons</b></div>
        {Object.entries(s.exit_reasons || {}).sort((a, b) => b[1] - a[1]).map(([r, c]) => (
          <div key={r} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, padding: '2px 0', color: '#c9d1d9' }}>
            <span className={r === 'sl_hit' ? 'loss' : r.includes('t2') ? 'win' : ''}>{r}</span>
            <b>{c} ({Math.round(c / s.total_trades * 100)}%)</b>
          </div>
        ))}
      </div>
      <div>
        <div className="muted" style={{ marginTop: 0, marginBottom: 8 }}><b>Year-by-Year P&amp;L</b></div>
        <table className="preds-tbl" style={{ marginTop: 0 }}>
          <thead>
            <tr><th>Year</th><th>Trades</th><th>Wins</th><th>Win Rate</th><th>P&L (Rs)</th></tr>
          </thead>
          <tbody>
            {Object.entries(s.by_year || {}).map(([yr, y]) => {
              const wr = y.trades ? Math.round(y.wins / y.trades * 100) : 0
              return (
                <tr key={yr}>
                  <td><b>{yr}</b></td>
                  <td>{y.trades}</td>
                  <td>{y.wins}</td>
                  <td className={wr > 50 ? 'win' : wr < 35 ? 'loss' : ''}>{wr}%</td>
                  <td className={y.pnl > 0 ? 'win' : 'loss'}>
                    Rs {(y.pnl / 1000).toFixed(0)}K
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>

        <div className="muted" style={{ marginTop: 16, marginBottom: 8 }}><b>Active Filters</b></div>
        <div style={{ fontSize: 12, color: '#8b949e', lineHeight: 1.8 }}>
          {s.config?.regime_filter && <div style={{ color: '#58a6ff' }}>Nifty &gt; 200 DMA regime filter</div>}
          {s.config?.min_rsi > 0 && <div>RSI &gt; {s.config.min_rsi}</div>}
          {s.config?.min_volume_ratio > 0 && <div>Volume &gt; {s.config.min_volume_ratio}x avg</div>}
          {s.config?.avoid_months && <div>Avoiding months: {s.config.avoid_months}</div>}
          {s.config?.max_dist_above_52w > 0 && <div>Max dist above 52W: {(s.config.max_dist_above_52w * 100).toFixed(0)}%</div>}
          <div>SL: {(s.config?.sl_pct * 100).toFixed(0)}% | R:R: {s.config?.rr_t1}x / {s.config?.rr_t2}x | Hold: {s.config?.max_hold_days}d</div>
          <div>Positions: {s.config?.max_open_positions} max ({s.config?.max_per_sector}/sector) | Risk: {(s.config?.risk_per_trade_pct * 100).toFixed(1)}%/trade</div>
        </div>
      </div>
    </div>
  )
}

function TradesTab({ trades }) {
  const [sort, setSort] = useState('date_desc')
  const sorted = [...trades].sort((a, b) => {
    if (sort === 'pnl_desc') return b.pnl_pct - a.pnl_pct
    if (sort === 'pnl_asc') return a.pnl_pct - b.pnl_pct
    if (sort === 'date_asc') return a.entry_date.localeCompare(b.entry_date)
    return b.entry_date.localeCompare(a.entry_date)
  })

  return (
    <>
      <div style={{ display: 'flex', gap: 8, marginBottom: 8, fontSize: 12 }}>
        <span className="muted" style={{ marginTop: 0 }}>Sort:</span>
        {[['date_desc', 'Newest'], ['date_asc', 'Oldest'], ['pnl_desc', 'Best'], ['pnl_asc', 'Worst']].map(([k, l]) => (
          <button key={k} onClick={() => setSort(k)}
            style={{ padding: '2px 8px', fontSize: 11, background: sort === k ? '#238636' : '#21262d', border: '1px solid #30363d', color: '#e6edf3', borderRadius: 4, cursor: 'pointer' }}>
            {l}
          </button>
        ))}
      </div>
      <div style={{ maxHeight: 420, overflowY: 'auto' }}>
        <table className="preds-tbl">
          <thead>
            <tr><th>Symbol</th><th>Sector</th><th>Entry</th><th>Exit</th><th>Days</th>
              <th>Entry Rs</th><th>Exit Rs</th><th>Reason</th><th>P&L %</th><th>P&L Rs</th></tr>
          </thead>
          <tbody>
            {sorted.slice(0, 150).map((t, i) => (
              <tr key={i}>
                <td><b>{t.symbol}</b></td>
                <td style={{ fontSize: 11, color: '#8b949e' }}>{t.sector}</td>
                <td>{t.entry_date}</td>
                <td>{t.exit_date}</td>
                <td>{t.holding_days}</td>
                <td>{t.entry_price?.toFixed(2)}</td>
                <td>{t.exit_price?.toFixed(2)}</td>
                <td>
                  <span className={`pill ${t.exit_reason?.includes('t2') ? 'buy_call' : t.exit_reason === 'sl_hit' ? 'buy_put' : 'no_trade'}`}>
                    {t.exit_reason}
                  </span>
                </td>
                <td className={t.pnl_pct > 0 ? 'win' : 'loss'}>{t.pnl_pct > 0 ? '+' : ''}{t.pnl_pct}%</td>
                <td className={t.pnl_abs > 0 ? 'win' : 'loss'}>Rs{t.pnl_abs?.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

function SectorsTab({ data }) {
  if (!data) return null
  return (
    <table className="preds-tbl">
      <thead>
        <tr><th>Sector</th><th>Trades</th><th>Wins</th><th>Win Rate</th><th>P&L (Rs)</th></tr>
      </thead>
      <tbody>
        {Object.entries(data).map(([sec, s]) => (
          <tr key={sec}>
            <td><b>{sec}</b></td>
            <td>{s.trades}</td>
            <td>{s.wins}</td>
            <td className={s.wins / s.trades > 0.5 ? 'win' : s.wins / s.trades < 0.3 ? 'loss' : ''}>
              {Math.round(s.wins / s.trades * 100)}%
            </td>
            <td className={s.pnl > 0 ? 'win' : 'loss'}>Rs {s.pnl?.toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function StocksTab({ data }) {
  if (!data) return null
  return (
    <table className="preds-tbl">
      <thead>
        <tr><th>Stock</th><th>Sector</th><th>Trades</th><th>Wins</th><th>Win Rate</th><th>P&L (Rs)</th></tr>
      </thead>
      <tbody>
        {Object.entries(data).map(([sym, s]) => (
          <tr key={sym}>
            <td><b>{sym}</b></td>
            <td style={{ fontSize: 11, color: '#8b949e' }}>{s.sector}</td>
            <td>{s.trades}</td>
            <td>{s.wins}</td>
            <td className={s.wins / s.trades > 0.5 ? 'win' : s.wins / s.trades < 0.3 ? 'loss' : ''}>
              {Math.round(s.wins / s.trades * 100)}%
            </td>
            <td className={s.pnl > 0 ? 'win' : 'loss'}>Rs {s.pnl?.toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
