import { Fragment } from 'react'

export default function StatsPanel({ stats }) {
  if (!stats || stats.total === 0) {
    return (
      <div className="card">
        <b>Replay stats</b>
        <div className="muted" style={{ marginTop: 8 }}>
          Click <b>Start Replay</b> to backtest the trained model on the last 1 year of daily bars.
          You'll see each day's prediction scored against the actual next-day move.
        </div>
      </div>
    )
  }

  const wr = (stats.win_rate * 100).toFixed(1)
  const prog = stats.total_bars > 0
    ? (((stats.current_idx - stats.start_idx) / (stats.total_bars - stats.start_idx)) * 100).toFixed(0)
    : 0

  return (
    <div className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <b>Replay stats</b>
        <span className="muted">{stats.running ? `running… ${prog}%` : 'stopped'}</span>
      </div>

      <div className="stats-row">
        <div className="stat"><div className="stat-num">{stats.total}</div><div className="stat-lbl">predictions</div></div>
        <div className="stat win"><div className="stat-num">{stats.wins}</div><div className="stat-lbl">wins</div></div>
        <div className="stat loss"><div className="stat-num">{stats.losses}</div><div className="stat-lbl">losses</div></div>
        <div className="stat"><div className="stat-num">{wr}%</div><div className="stat-lbl">win rate</div></div>
      </div>

      {stats.by_class && (
        <div className="kv" style={{ marginTop: 12 }}>
          {['BUY_CALL', 'BUY_PUT', 'NO_TRADE'].map((c) => {
            const b = stats.by_class[c] || {}
            const p = ((b.precision || 0) * 100).toFixed(0)
            return (
              <Fragment key={c}>
                <span>{c}</span>
                <b>{b.n || 0} preds · {p}% precision</b>
              </Fragment>
            )
          })}
        </div>
      )}

      {stats.threshold_sweep && stats.threshold_sweep.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div className="muted" style={{ marginTop: 0, marginBottom: 8 }}>
            <b>Confidence-gated win rate</b> — if you only took directional trades above this confidence:
          </div>
          <table className="preds-tbl">
            <thead>
              <tr><th>Min conf</th><th>Trades taken</th><th>Wins</th><th>Losses</th><th>Win rate</th></tr>
            </thead>
            <tbody>
              {stats.threshold_sweep.map((t) => {
                const wr = (t.win_rate * 100).toFixed(1)
                const wrCls = t.win_rate > 0.55 ? 'win' : t.win_rate < 0.45 ? 'loss' : ''
                return (
                  <tr key={t.threshold}>
                    <td>{(t.threshold * 100).toFixed(0)}%</td>
                    <td>{t.trades}</td>
                    <td className="win">{t.wins}</td>
                    <td className="loss">{t.losses}</td>
                    <td className={wrCls}>{wr}%</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {stats.latest && stats.latest.length > 0 && (
        <table className="preds-tbl">
          <thead>
            <tr><th>Date</th><th>Pred</th><th>Conf</th><th>Move</th><th>Outcome</th></tr>
          </thead>
          <tbody>
            {stats.latest.map((p) => {
              const movePct = (p.move_pct * 100).toFixed(2)
              const moveCls = p.move_pct > 0 ? 'up' : p.move_pct < 0 ? 'down' : ''
              const outClass =
                p.outcome === 'WIN' ? 'win' :
                p.outcome?.startsWith('LOSS') ? 'loss' :
                p.outcome === 'MISSED' ? 'missed' : ''
              return (
                <tr key={p.idx}>
                  <td>{(p.datetime || '').slice(0, 10)}</td>
                  <td><span className={`pill ${p.prediction.toLowerCase()}`}>{p.prediction}</span></td>
                  <td>{(p.confidence * 100).toFixed(0)}%</td>
                  <td className={moveCls}>{movePct}%</td>
                  <td className={outClass}>{p.outcome}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}
