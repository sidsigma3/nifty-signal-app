import { useEffect, useState } from 'react'
import SignalCard from './SignalCard.jsx'
import ChartView from './ChartView.jsx'
import StatsPanel from './StatsPanel.jsx'
import AutoTradePanel from './AutoTradePanel.jsx'
import BacktestPanel from './BacktestPanel.jsx'
import ScannerPanel from './ScannerPanel.jsx'

const API = import.meta.env.DEV ? '/api' : ''

export default function SignalDashboard() {
  const [health, setHealth] = useState(null)
  const [signal, setSignal] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [replayStats, setReplayStats] = useState(null)
  const [replayBusy, setReplayBusy] = useState(false)
  const [invert, setInvert] = useState(false)
  const [page, setPage] = useState('signals') // signals | backtest | scanner

  useEffect(() => {
    fetch(`${API}/health`).then(r => r.json()).then(setHealth).catch(() => {})
  }, [])

  useEffect(() => {
    let alive = true
    async function poll() {
      try {
        const res = await fetch(`${API}/replay/stats`)
        const data = await res.json()
        if (alive) setReplayStats(data)
      } catch {}
    }
    const id = setInterval(poll, 1000)
    poll()
    return () => { alive = false; clearInterval(id) }
  }, [])

  async function fetchSignal() {
    setLoading(true); setError(null)
    try {
      const res = await fetch(`${API}/predict`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ csv_name: 'nifty50_daily.csv', use_last_n: 1 }),
      })
      if (!res.ok) throw new Error(await res.text())
      setSignal(await res.json())
    } catch (e) {
      setError(String(e.message || e))
    } finally { setLoading(false) }
  }

  async function startReplay() {
    setReplayBusy(true)
    try {
      const res = await fetch(`${API}/replay/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ csv_name: 'nifty50_daily.csv', speed_seconds: 1.5, last_n: 60, invert }),
      })
      if (!res.ok) alert(`Start failed: ${await res.text()}`)
    } finally { setReplayBusy(false) }
  }

  async function stopReplay() {
    setReplayBusy(true)
    try { await fetch(`${API}/replay/stop`, { method: 'POST' }) }
    finally { setReplayBusy(false) }
  }

  async function placeOrder(side) {
    const res = await fetch(`${API}/order/place`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        instrument_token: 'NSE_FO|NIFTY-CE-25200',
        side, quantity: 25, order_type: 'MARKET', price: 0,
      }),
    })
    const data = await res.json()
    alert(`Order ${data.accepted ? 'accepted' : 'rejected'}: ${data.reason}${data.paper ? ' (paper)' : ''}`)
  }

  const replayRunning = replayStats?.running

  return (
    <div className="container">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
        <h1 style={{ margin: 0 }}>Nifty 50 Signal Dashboard</h1>
        <div className="nav-tabs">
          {[
            ['signals', 'Signals & Trade'],
            ['backtest', '52W Backtest'],
            ['scanner', 'Live Scanner'],
          ].map(([k, label]) => (
            <button key={k} onClick={() => setPage(k)}
              className={page === k ? 'nav-active' : ''}>
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="health">
        {health ? (
          <>
            Models: {health.models_loaded ? 'ok' : 'x'} ·
            Kill switch: {health.kill_switch_armed ? 'armed' : 'tripped'} ·
            Mode: <span className={health.live_trade === 'true' ? 'live' : 'paper'}>
              {health.live_trade === 'true' ? 'LIVE' : 'PAPER'}
            </span>
            {replayRunning && <> · <b style={{ color: '#58a6ff' }}>REPLAY ACTIVE</b></>}
          </>
        ) : 'connecting...'}
      </div>

      {/* ===== SIGNALS PAGE ===== */}
      {page === 'signals' && (
        <>
          <div className="replay-controls">
            <button className="primary" onClick={startReplay} disabled={replayBusy || replayRunning}>
              Start Replay
            </button>
            <button className="danger" onClick={stopReplay} disabled={replayBusy || !replayRunning}>
              Stop Replay
            </button>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#e6edf3', fontSize: 13 }}>
              <input type="checkbox" checked={invert}
                onChange={(e) => setInvert(e.target.checked)} disabled={replayRunning} />
              Invert signals
            </label>
            <span className="muted">
              Replays last 60 days (out-of-sample) at 1.5s/bar
            </span>
          </div>

          <div className="grid">
            <SignalCard signal={signal} loading={loading} error={error}
              onRefresh={fetchSignal} onPlace={placeOrder} />
            <ChartView />
          </div>

          <div style={{ marginTop: 20 }}>
            <AutoTradePanel />
          </div>

          <div style={{ marginTop: 20 }}>
            <StatsPanel stats={replayStats} />
          </div>
        </>
      )}

      {/* ===== BACKTEST PAGE ===== */}
      {page === 'backtest' && (
        <div style={{ marginTop: 8 }}>
          <BacktestPanel />
        </div>
      )}

      {/* ===== SCANNER PAGE ===== */}
      {page === 'scanner' && (
        <div style={{ marginTop: 8 }}>
          <ScannerPanel />
        </div>
      )}
    </div>
  )
}
