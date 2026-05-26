import { useEffect, useState } from 'react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'

export default function ChartView() {
  const [points, setPoints] = useState([])
  const [mode, setMode] = useState('stub')  // 'stub' | 'replay' | 'live'
  const [latestLtp, setLatestLtp] = useState(null)

  useEffect(() => {
    let alive = true
    async function poll() {
      try {
        const res = await fetch('/api/feed/latest')
        const data = await res.json()
        if (!alive) return

        if (data?.replay) {
          // Replay mode — historical close + datetime
          const ltp = Number(data.ltp)
          const label = (data.datetime || '').slice(0, 10)
          setMode('replay')
          setLatestLtp(ltp)
          setPoints((p) => {
            if (p.length && p[p.length - 1].t === label) return p
            return [...p.slice(-249), { t: label, v: ltp }]
          })
        } else if (data?.mode === 'live' && data?.ltp != null) {
          // Live Upstox LTP
          const ltp = Number(data.ltp)
          const label = new Date().toLocaleTimeString('en-IN', { hour12: false })
          setMode('live')
          setLatestLtp(ltp)
          setPoints((p) => [...p.slice(-179), { t: label, v: ltp }])
        } else {
          // Stub feed — synthetic counter
          const v = data?.tick ?? data?.ltp ?? null
          if (v != null) {
            setMode('stub')
            setLatestLtp(null)
            setPoints((p) => [...p.slice(-99), { t: new Date().toLocaleTimeString(), v: Number(v) }])
          }
        }
      } catch {}
    }
    const id = setInterval(poll, 1000)
    poll()
    return () => { alive = false; clearInterval(id) }
  }, [])

  const title =
    mode === 'replay' ? 'Nifty 50 — replay' :
    mode === 'live'   ? 'Nifty 50 — LIVE' :
                        'Nifty live (stub feed)'

  return (
    <div className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <b>
          {title}
          {mode === 'live' && <span style={{ marginLeft: 8, color: '#f85149', fontSize: 11, fontWeight: 700 }}>● LIVE</span>}
        </b>
        <span className="muted">
          {latestLtp != null ? `₹${latestLtp.toFixed(2)} · ` : ''}
          {points.length ? `${points.length} pts` : 'awaiting feed'}
        </span>
      </div>
      <div style={{ width: '100%', height: 280, marginTop: 12 }}>
        <ResponsiveContainer>
          <LineChart data={points}>
            <CartesianGrid strokeDasharray="3 3" stroke="#30363d" />
            <XAxis dataKey="t" stroke="#8b949e" tick={{ fontSize: 10 }} hide={points.length < 5} />
            <YAxis domain={['auto', 'auto']} stroke="#8b949e" tick={{ fontSize: 11 }} />
            <Tooltip contentStyle={{ background: '#161b22', border: '1px solid #30363d' }} />
            <Line
              type="monotone"
              dataKey="v"
              stroke={mode === 'live' ? '#3fb950' : '#58a6ff'}
              dot={false}
              strokeWidth={2}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
