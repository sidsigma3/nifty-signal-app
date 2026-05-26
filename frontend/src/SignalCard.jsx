export default function SignalCard({ signal, loading, error, onRefresh, onPlace }) {
  const pred = signal?.prediction ?? '—'
  const conf = signal?.confidence ?? 0
  const cls = pred.toLowerCase()
  const side = pred === 'BUY_CALL' ? 'BUY' : pred === 'BUY_PUT' ? 'SELL' : null

  return (
    <div className="card signal-card">
      <div className="badge-row">
        <span className={`badge ${cls}`}>{pred}</span>
      </div>
      <div className="confidence-bar"><div style={{ width: `${(conf * 100).toFixed(0)}%` }} /></div>
      <div className="muted">Confidence: {(conf * 100).toFixed(1)}%</div>

      {signal?.indicators && (
        <div className="kv" style={{ marginTop: 12 }}>
          <span>RSI(14)</span><b>{signal.indicators.rsi_14?.toFixed(2)}</b>
          <span>MACD hist</span><b>{signal.indicators.macd_hist?.toFixed(3)}</b>
          <span>EMA 9/21</span><b>{signal.indicators.ema_cross_9_21 ? 'bull' : 'bear'}</b>
          <span>ATR(14)</span><b>{signal.indicators.atr_14?.toFixed(2)}</b>
          <span>BB %B</span><b>{signal.indicators.bb_pct_b?.toFixed(2)}</b>
          <span>DTE</span><b>{signal.indicators.dte}</b>
        </div>
      )}

      {signal?.explanation && (
        <div className="explanation">{signal.explanation}</div>
      )}

      {error && <div className="explanation" style={{ borderLeftColor: '#f85149' }}>{error}</div>}

      <div className="actions">
        <button onClick={onRefresh} disabled={loading}>
          {loading ? 'Predicting…' : 'Get Signal'}
        </button>
        <button
          className="primary"
          disabled={!side || loading}
          onClick={() => onPlace(side)}
        >
          Place Order
        </button>
        <button className="danger" disabled={loading}>Skip</button>
      </div>
    </div>
  )
}
