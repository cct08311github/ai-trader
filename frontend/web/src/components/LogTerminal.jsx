import React, { useEffect, useMemo, useRef, useState } from 'react'

const DEFAULT_API_BASE = (typeof window !== 'undefined' && window.location.hostname.includes('tail'))
  ? `https://${window.location.hostname}:8080`
  : 'http://localhost:8080'

import { getToken } from '../lib/auth'

function formatTs(ts) {
  const n = Number(ts)
  if (!Number.isFinite(n)) return ''
  return new Date(n).toLocaleString('zh-TW', { hour12: false })
}

function safeJsonParse(s) {
  try {
    return JSON.parse(s)
  } catch {
    return null
  }
}

export default function LogTerminal() {
  const apiBase = useMemo(() => {
    const base = import.meta?.env?.VITE_API_BASE || DEFAULT_API_BASE
    return String(base).replace(/\/$/, '')
  }, [])
  const token = getToken()

  const [connected, setConnected] = useState(false)
  const [paused, setPaused] = useState(false)
  const [level, setLevel] = useState('ALL')
  const [query, setQuery] = useState('')
  const [logs, setLogs] = useState([])
  const [err, setErr] = useState(null)

  const boxRef = useRef(null)
  const lastEventIdRef = useRef(null)

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (logs || []).filter(l => {
      if (level !== 'ALL' && String(l?.level || '').toUpperCase() !== level) return false
      if (!q) return true
      const hay = `${l?.message || ''} ${l?.agent || ''} ${l?.model || ''} ${l?.trace_id || ''}`.toLowerCase()
      return hay.includes(q)
    })
  }, [logs, level, query])

  useEffect(() => {
    if (paused) return
    const el = boxRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [filtered.length, paused])

  useEffect(() => {
    if (paused) return

    const url = `${apiBase}/api/stream/logs${token ? `?token=${token}` : ''}`
    const es = new EventSource(url)

    const onOpen = () => {
      setConnected(true)
      setErr(null)
    }

    const onError = () => {
      setConnected(false)
      setErr('連線中斷，將自動重連...')
    }

    const onHeartbeat = e => {
      const payload = safeJsonParse(e.data) || { level: 'INFO', message: 'heartbeat', ts: Date.now(), type: 'heartbeat' }
      // Don’t spam UI with heartbeats; keep only the latest heartbeat.
      setLogs(prev => {
        const next = prev.filter(x => x?.type !== 'heartbeat')
        next.push(payload)
        return next.slice(-500)
      })
    }

    const onLog = e => {
      const payload = safeJsonParse(e.data)
      if (!payload) return
      if (e?.lastEventId) lastEventIdRef.current = e.lastEventId
      setLogs(prev => {
        const next = [...prev, payload]
        return next.slice(-500)
      })
    }

    es.addEventListener('open', onOpen)
    es.addEventListener('error', onError)
    es.addEventListener('heartbeat', onHeartbeat)
    es.addEventListener('log', onLog)

    return () => {
      es.close()
      setConnected(false)
    }
  }, [apiBase, paused])

  const clear = () => setLogs([])

  const badgeCls = connected ? 'bg-emerald-900/40 text-emerald-300 border-emerald-800' : 'bg-rose-900/40 text-rose-300 border-rose-800'

  return (
    <div className="space-y-3 rounded-2xl border border-slate-800 bg-slate-900/40 p-5 shadow-panel">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-semibold">即時日誌終端機 (SSE)</div>
          <div className="mt-1 text-xs text-slate-400">決策日誌 llm_traces + 系統心跳。預設不顯示 prompt/response（避免敏感資訊外洩）。</div>
        </div>
        <div className={`shrink-0 rounded-full border px-3 py-1 text-xs ${badgeCls}`}>{connected ? '已連線' : '未連線'}</div>
      </div>

      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={level}
            onChange={e => setLevel(e.target.value)}
            className="rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2 text-xs text-slate-200"
          >
            <option value="ALL">ALL</option>
            <option value="INFO">INFO</option>
            <option value="WARN">WARN</option>
            <option value="ERROR">ERROR</option>
          </select>

          <input
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="搜尋 message / agent / model / trace_id"
            className="w-72 max-w-full rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2 text-xs text-slate-200 placeholder:text-slate-500"
          />
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setPaused(p => !p)}
            className={`rounded-lg px-3 py-2 text-xs font-medium transition-all ${paused ? 'bg-amber-600 hover:bg-amber-500 text-white' : 'bg-slate-800 hover:bg-slate-700 text-slate-200'
              }`}
          >
            {paused ? '▶ 繼續' : '⏸ 暫停'}
          </button>
          <button onClick={clear} className="rounded-lg bg-slate-800 px-3 py-2 text-xs font-medium text-slate-200 hover:bg-slate-700 transition-all">
            清除
          </button>
        </div>
      </div>

      {err && <div className="rounded-lg border border-rose-800 bg-rose-900/20 p-3 text-xs text-rose-300">{err}</div>}

      <div ref={boxRef} className="h-64 sm:h-80 md:h-96 overflow-auto rounded-xl border border-slate-800 bg-slate-950/40 p-3 font-mono text-xs">
        {filtered.length === 0 ? (
          <div className="text-slate-500">尚無日誌（等待 SSE 推送...）</div>
        ) : (
          <div className="space-y-1">
            {filtered.map((l, idx) => {
              const lv = String(l?.level || 'INFO').toUpperCase()
              const color = lv === 'ERROR' ? 'text-rose-300' : lv === 'WARN' ? 'text-amber-300' : 'text-slate-200'
              const meta = [l?.agent, l?.model, l?.trace_id].filter(Boolean).join(' · ')
              return (
                <div key={`${l?.ts || idx}-${idx}`} className="flex gap-3">
                  <div className="w-28 sm:w-44 shrink-0 text-slate-500">{formatTs(l?.ts)}</div>
                  <div className={`w-14 shrink-0 ${color}`}>{lv}</div>
                  <div className="min-w-0 flex-1">
                    <div className={`${color} break-words`}>{l?.message || JSON.stringify(l)}</div>
                    {meta && <div className="mt-0.5 text-[11px] text-slate-500 break-words">{meta}</div>}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      <div className="text-[11px] text-slate-500">
        <div>
          API: <code className="text-slate-300">{apiBase}/api/stream/logs</code>
        </div>
        <div>
          Cursor (Last-Event-ID): <code className="text-slate-300">{String(lastEventIdRef.current || '-')}</code>
        </div>
      </div>
    </div>
  )
}
