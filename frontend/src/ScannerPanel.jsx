import { useEffect, useState } from 'react'

const API = import.meta.env.DEV ? '/api' : ''

export default function ScannerPanel() {
  const [signals, setSignals] = useState([])
  const [loading, setLoading] = useState(false)
  const [lastScan, setLastScan] = useState(null)

  async function scan() {
    setLoading(true)
    try {
      const res = await fetch(`${API}/backtest/scanner`)
      const data = await res.json()
      setSignals(data.signals || [])
      setLastScan(new Date().toLocaleTimeString())
    } catch {}
    setLoading(false)
  }

  useEffect(() => { scan() }, [])

  // Compute signal quality
  function grade(s) {
    let score = 0
    let reasons = []

    // RSI momentum
    if (s.rsi >= 70) { score += 2; reasons.push('Strong RSI') }
    else if (s.rsi >= 55) { score += 1; reasons.push('OK RSI') }
    else { reasons.push('Weak RSI') }

    // Fresh breakout (not over-extended)
    if (s.dist_pct <= 2) { score += 2; reasons.push('Fresh breakout') }
    else if (s.dist_pct <= 5) { score += 1; reasons.push('Moderate extension') }
    else { score -= 1; reasons.push('Over-extended') }

    // Volume confirmation
    const volRatio = s.vol_ma20 > 0 ? s.volume / s.vol_ma20 : 1
    if (volRatio >= 2) { score += 2; reasons.push(`${volRatio.toFixed(1)}x volume`) }
    else if (volRatio >= 1.2) { score += 1; reasons.push('Good volume') }
    else { reasons.push('Low volume') }

    // Volatility (ATR)
    if (s.atr_pct >= 1.5 && s.atr_pct <= 3) { score += 1; reasons.push('Good ATR') }

    const signal = score >= 5 ? 'STRONG' : score >= 3 ? 'GO' : 'REVIEW'
    return { signal, score, reasons, volRatio }
  }

  return (
    <div className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <b style={{ fontSize: 16 }}>52-Week Breakout Scanner</b>
          <span className="muted" style={{ marginLeft: 8, marginTop: 0 }}>
            {signals.length} stock{signals.length !== 1 ? 's' : ''} at 52-week highs
          </span>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {lastScan && <span className="muted" style={{ marginTop: 0 }}>Scanned: {lastScan}</span>}
          <button onClick={scan} disabled={loading} style={{ fontSize: 12, padding: '4px 12px' }}>
            {loading ? 'Scanning...' : 'Refresh'}
          </button>
        </div>
      </div>

      {signals.length === 0 && !loading && (
        <div style={{ marginTop: 16, padding: 20, textAlign: 'center', color: '#8b949e' }}>
          <div style={{ fontSize: 32, marginBottom: 8 }}>--</div>
          <div>No stocks breaking 52-week highs today.</div>
          <div style={{ marginTop: 4, fontSize: 12 }}>Market may be in consolidation or correction. Wait for setups.</div>
        </div>
      )}

      {signals.length > 0 && (
        <>
          <table className="preds-tbl" style={{ marginTop: 12 }}>
            <thead>
              <tr>
                <th>Signal</th>
                <th>Stock</th>
                <th>Sector</th>
                <th>Close</th>
                <th>52W High</th>
                <th>% Above</th>
                <th>RSI</th>
                <th>Vol Ratio</th>
                <th>ATR %</th>
                <th>Factors</th>
              </tr>
            </thead>
            <tbody>
              {signals.map((s) => {
                const g = grade(s)
                const pillCls = g.signal === 'STRONG' ? 'buy_call' : g.signal === 'GO' ? 'no_trade' : 'buy_put'
                return (
                  <tr key={s.symbol}>
                    <td>
                      <span className={`pill ${pillCls}`} style={{ fontSize: 10, fontWeight: 700 }}>
                        {g.signal}
                      </span>
                    </td>
                    <td><b>{s.symbol}</b></td>
                    <td style={{ fontSize: 11, color: '#8b949e' }}>{s.sector}</td>
                    <td>Rs {s.close?.toLocaleString()}</td>
                    <td style={{ color: '#8b949e' }}>Rs {s.high_52w?.toLocaleString()}</td>
                    <td className="win">+{s.dist_pct}%</td>
                    <td className={s.rsi >= 60 ? 'win' : s.rsi < 50 ? 'loss' : ''}>{s.rsi}</td>
                    <td className={g.volRatio >= 1.5 ? 'win' : ''}>{g.volRatio.toFixed(1)}x</td>
                    <td>{s.atr_pct}%</td>
                    <td style={{ fontSize: 11, color: '#8b949e', maxWidth: 180 }}>
                      {g.reasons.slice(0, 3).join(' · ')}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>

          {/* Trade plan for top signals */}
          {signals.filter(s => grade(s).signal !== 'REVIEW').length > 0 && (
            <div style={{ marginTop: 16 }}>
              <div className="muted" style={{ marginTop: 0, marginBottom: 8 }}><b>TRADE PLAN (5% SL, 2:1 / 3:1 R:R)</b></div>
              {signals.filter(s => grade(s).signal !== 'REVIEW').map(s => {
                const sl = s.close * 0.95
                const risk = s.close - sl
                const t1 = s.close + risk * 2
                const t2 = s.close + risk * 3
                const qty = Math.floor(10000 / risk)  // Rs 10K risk budget
                return (
                  <div key={s.symbol} className="explanation" style={{ marginTop: 8, borderLeftColor: grade(s).signal === 'STRONG' ? '#3fb950' : '#58a6ff' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <b>{s.symbol}</b>
                      <span className={`pill ${grade(s).signal === 'STRONG' ? 'buy_call' : 'no_trade'}`}>{grade(s).signal}</span>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginTop: 8, fontSize: 13 }}>
                      <div>Entry: <b>Rs {s.close.toFixed(2)}</b></div>
                      <div>SL: <b style={{ color: '#f85149' }}>Rs {sl.toFixed(2)}</b></div>
                      <div>T1 (50%): <b style={{ color: '#3fb950' }}>Rs {t1.toFixed(2)}</b></div>
                      <div>T2 (50%): <b style={{ color: '#3fb950' }}>Rs {t2.toFixed(2)}</b></div>
                    </div>
                    <div className="muted" style={{ marginTop: 6 }}>
                      Risk/share: Rs {risk.toFixed(2)} | Qty (Rs 10K risk): {qty} shares | Capital: Rs {(qty * s.close).toLocaleString()}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </>
      )}

      <div className="muted" style={{ marginTop: 12 }}>
        <b>Signal grading:</b> STRONG = RSI&gt;70 + fresh breakout + high volume. GO = decent setup. REVIEW = weak factors.
        Always check news/earnings before entry. Not SEBI registered advice.
      </div>
    </div>
  )
}
