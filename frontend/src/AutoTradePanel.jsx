import { useEffect, useState } from 'react'

const API = import.meta.env.DEV ? '/api' : ''

export default function AutoTradePanel() {
  const [stats, setStats] = useState(null)
  const [minConf, setMinConf] = useState(0.40)
  const [capital, setCapital] = useState(10000)
  const [targetPct, setTargetPct] = useState(50)  // % on premium
  const [stopPct, setStopPct] = useState(30)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let alive = true
    async function poll() {
      try {
        const r = await fetch(`${API}/auto_trade/stats`)
        const d = await r.json()
        if (alive) setStats(d)
      } catch {}
    }
    const id = setInterval(poll, 2000)
    poll()
    return () => { alive = false; clearInterval(id) }
  }, [])

  async function start() {
    setBusy(true)
    try {
      await fetch(`${API}/auto_trade/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          min_confidence: minConf,
          capital_inr: capital,
          target_pct: targetPct / 100,
          stop_pct: stopPct / 100,
        }),
      })
    } finally { setBusy(false) }
  }

  async function stop() {
    if (stats?.trades_open > 0) {
      if (!confirm(`Stop will close ${stats.trades_open} open position(s) at the current premium. Continue?`)) return
    }
    setBusy(true)
    try { await fetch(`${API}/auto_trade/stop`, { method: 'POST' }) }
    finally { setBusy(false) }
  }

  async function reset() {
    if (!confirm('Reset all trade history?')) return
    setBusy(true)
    try { await fetch(`${API}/auto_trade/reset`, { method: 'POST' }) }
    finally { setBusy(false) }
  }

  const running = stats?.running
  const totalPnlCls = (stats?.total_pnl_incl_open ?? 0) > 0 ? 'win' : (stats?.total_pnl_incl_open ?? 0) < 0 ? 'loss' : ''
  const realizedCls = (stats?.realized_pnl ?? 0) > 0 ? 'win' : (stats?.realized_pnl ?? 0) < 0 ? 'loss' : ''
  const wr = ((stats?.win_rate ?? 0) * 100).toFixed(1)

  return (
    <div className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <b>Auto Paper Trader — Nifty Options</b>
        <span className="muted" style={{ marginTop: 0 }}>
          {running ? (
            <span style={{ color: '#3fb950', fontWeight: 700 }}>● RUNNING</span>
          ) : 'stopped'}
          {stats?.status_msg && <> · <i>{stats.status_msg}</i></>}
        </span>
      </div>

      <div className="auto-controls">
        <label>
          Capital (₹):{' '}
          <input
            type="number" min="2000" step="1000"
            value={capital}
            onChange={(e) => setCapital(Number(e.target.value))}
            disabled={running}
            style={{ width: 90 }}
          />
        </label>
        <label>
          Min conf (%):{' '}
          <input
            type="number" min="0" max="100" step="5"
            value={Math.round(minConf * 100)}
            onChange={(e) => setMinConf(Number(e.target.value) / 100)}
            disabled={running}
            style={{ width: 60 }}
          />
        </label>
        <label>
          Target (% premium):{' '}
          <input
            type="number" min="10" max="200" step="5"
            value={targetPct}
            onChange={(e) => setTargetPct(Number(e.target.value))}
            disabled={running}
            style={{ width: 60 }}
          />
        </label>
        <label>
          Stop (% premium):{' '}
          <input
            type="number" min="5" max="100" step="5"
            value={stopPct}
            onChange={(e) => setStopPct(Number(e.target.value))}
            disabled={running}
            style={{ width: 60 }}
          />
        </label>

        <button className="primary" onClick={start} disabled={busy || running}>Start</button>
        <button className="danger" onClick={stop} disabled={busy || !running}>Stop &amp; Close All</button>
        <button onClick={reset} disabled={busy || running}>Reset History</button>
      </div>

      {stats && (
        <div className="stats-row" style={{ marginTop: 14 }}>
          <div className="stat"><div className="stat-num">{stats.trades_total}</div><div className="stat-lbl">total</div></div>
          <div className="stat"><div className="stat-num">{stats.trades_open}</div><div className="stat-lbl">open</div></div>
          <div className="stat win"><div className="stat-num">{stats.wins}</div><div className="stat-lbl">wins</div></div>
          <div className="stat loss"><div className="stat-num">{stats.losses}</div><div className="stat-lbl">losses</div></div>
          <div className="stat"><div className="stat-num">{wr}%</div><div className="stat-lbl">win rate</div></div>
          <div className={`stat ${totalPnlCls}`}>
            <div className="stat-num">{(stats.total_pnl_incl_open ?? 0).toFixed(0)}</div>
            <div className="stat-lbl">total P&amp;L (₹)</div>
          </div>
          <div className={`stat ${realizedCls}`}>
            <div className="stat-num">{(stats.realized_pnl ?? 0).toFixed(0)}</div>
            <div className="stat-lbl">realized (₹)</div>
          </div>
        </div>
      )}

      {stats?.open_positions?.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <div className="muted" style={{ marginTop: 0, marginBottom: 6 }}><b>Open positions</b></div>
          <table className="preds-tbl">
            <thead>
              <tr>
                <th>#</th><th>Entered</th><th>Contract</th><th>Conf</th><th>Lots/Qty</th>
                <th>Entry ₹</th><th>Now ₹</th><th>Target ₹</th><th>Stop ₹</th><th>P&amp;L</th>
              </tr>
            </thead>
            <tbody>
              {stats.open_positions.map((t) => {
                const cls = (t.pnl ?? 0) > 0 ? 'win' : (t.pnl ?? 0) < 0 ? 'loss' : ''
                return (
                  <tr key={t.id}>
                    <td>#{t.id}</td>
                    <td>{(t.entry_time || '').slice(11, 19)}</td>
                    <td>
                      <span className={`pill ${t.direction.toLowerCase()}`}>{t.strike} {t.option_side}</span>
                      {t.moneyness && <span style={{ marginLeft: 4, fontSize: 9, color: t.moneyness === 'ATM' ? '#3fb950' : '#d29922' }}>{t.moneyness}</span>}
                      <div style={{ fontSize: 10, color: '#8b949e', marginTop: 2 }}>exp {t.expiry}</div>
                    </td>
                    <td>{(t.confidence * 100).toFixed(0)}%</td>
                    <td>{t.n_lots}×{t.qty / t.n_lots} = {t.qty}</td>
                    <td>{t.entry_premium?.toFixed(2)}</td>
                    <td>{t.current_premium?.toFixed(2)}</td>
                    <td>{t.target_premium?.toFixed(2)}</td>
                    <td>{t.stop_premium?.toFixed(2)}</td>
                    <td className={cls}>{t.pnl?.toFixed(0)} ({(t.pnl_pct * 100).toFixed(1)}%)</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {stats?.recent_closed?.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <div className="muted" style={{ marginTop: 0, marginBottom: 6 }}><b>Recent closed</b></div>
          <table className="preds-tbl">
            <thead>
              <tr>
                <th>#</th><th>In</th><th>Out</th><th>Contract</th><th>Qty</th>
                <th>Entry ₹</th><th>Exit ₹</th><th>Outcome</th><th>P&amp;L</th>
              </tr>
            </thead>
            <tbody>
              {stats.recent_closed.map((t) => {
                const outCls =
                  t.status === 'win_target' ? 'win' :
                  t.status === 'loss_stop' ? 'loss' :
                  (t.status === 'exit_time' || t.status === 'exit_manual') ? 'missed' : ''
                const pnlCls = (t.pnl ?? 0) > 0 ? 'win' : (t.pnl ?? 0) < 0 ? 'loss' : ''
                return (
                  <tr key={t.id}>
                    <td>#{t.id}</td>
                    <td>{(t.entry_time || '').slice(11, 19)}</td>
                    <td>{(t.exit_time || '').slice(11, 19)}</td>
                    <td><span className={`pill ${t.direction.toLowerCase()}`}>{t.strike} {t.option_side}</span>
                      {t.moneyness && <span style={{ marginLeft: 4, fontSize: 9, color: t.moneyness === 'ATM' ? '#3fb950' : '#d29922' }}>{t.moneyness}</span>}</td>
                    <td>{t.qty}</td>
                    <td>{t.entry_premium?.toFixed(2)}</td>
                    <td>{t.exit_premium?.toFixed(2)}</td>
                    <td className={outCls}>{t.status}</td>
                    <td className={pnlCls}>{t.pnl?.toFixed(0)} ({(t.pnl_pct * 100).toFixed(1)}%)</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
