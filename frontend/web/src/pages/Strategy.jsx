/**
 * Strategy.jsx -- War Room Layout
 *
 * Complete layout restructure:
 *   Hero: Active proposals expanded by default
 *   Split view: Bull thesis (5 cols) | Arbiter (2 cols) | Bear thesis (5 cols)
 *   Below: Proposal queue as compact rows with status dots
 *   Committee debate: conversation-style chat bubbles
 *   LLM trace: collapsible terminal-style monospace blocks
 *
 * All data fetching and state management preserved from original.
 */

import React, { useEffect, useMemo, useState, Fragment } from 'react'
import { useStreamApiBase, useStrategyData } from '../lib/strategyApi'
import { CheckCircle2, XCircle, Clock, ChevronDown, ChevronRight, MessageSquare, Target, Save, FileSignature, ShieldAlert, Cpu, Copy, Check, FileText, Lightbulb } from 'lucide-react'
import { authFetch, getApiBase, getToken } from '../lib/auth'
import { useToast } from '../components/ToastProvider'
import { useSymbolNames, formatSymbol } from '../lib/symbolNames'
import EmptyState from '../components/EmptyState'
import LoadingSpinner from '../components/LoadingSpinner'
import ErrorState from '../components/ErrorState'

function formatUnixSec(sec) {
  const n = Number(sec)
  if (!Number.isFinite(n) || n <= 0) return ''
  const ms = n > 1e12 ? n : n * 1000
  return new Date(ms).toLocaleString('zh-TW', { hour12: false })
}

function safeJsonParse(s) {
  try { return JSON.parse(s) } catch { return null }
}

/* ── Status Tag with dot ─────────────────────────────────── */
function StatusTag({ status }) {
  const s = String(status || '').toLowerCase() || 'unknown'
  const map = {
    pending:  { dot: 'bg-[rgb(var(--warn))]', text: 'text-[rgb(var(--warn))]', label: 'PENDING' },
    approved: { dot: 'bg-[rgb(var(--up))]', text: 'text-[rgb(var(--up))]', label: 'APPROVED' },
    rejected: { dot: 'bg-[rgb(var(--danger))]', text: 'text-[rgb(var(--danger))]', label: 'REJECTED' },
    executed: { dot: 'bg-[rgb(var(--info))]', text: 'text-[rgb(var(--info))]', label: 'EXECUTED' },
    unknown:  { dot: 'bg-[rgb(var(--muted))]', text: 'text-[rgb(var(--muted))]', label: s.toUpperCase() },
  }
  const t = map[s] || map.unknown
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`h-2 w-2 rounded-full ${t.dot}`} />
      <span className={`font-mono text-[10px] font-bold uppercase tracking-widest ${t.text}`}>{t.label}</span>
    </span>
  )
}

/* ── Rating Card -- large dramatic display ───────────────── */
function RatingHero({ rating, basis }) {
  const r = String(rating || '').toUpperCase()
  const colorVar = { A: '--up', B: '--warn', C: '--danger' }[r] || '--muted'

  return (
    <div className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.4)]" style={{ borderRadius: '4px', borderLeft: `4px solid rgb(var(${colorVar}))` }}>
      <div className="flex items-center gap-6 px-6 py-5">
        <div className="font-mono text-7xl font-black tabular-nums tracking-tight"
          style={{
            color: `rgb(var(${colorVar}))`,
            filter: r === 'A' ? 'drop-shadow(0 0 8px rgb(var(--up)))' : 'none',
            lineHeight: 1,
          }}
        >{r || '-'}</div>
        <div className="flex-1 min-w-0">
          <div className="font-mono text-[9px] uppercase tracking-[0.2em] text-[rgb(var(--muted))]">MARKET RATING</div>
          <div className="mt-2 font-mono text-[11px] leading-relaxed text-[rgb(var(--muted))] line-clamp-3">{basis || '(No rating basis)'}</div>
        </div>
      </div>
    </div>
  )
}

/* ── Bull vs Bear Split View ─────────────────────────────── */
function DebateHeroSection() {
  const [debates, setDebates] = useState([])
  const [date, setDate] = useState('today')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setLoading(true)
    authFetch(`${getApiBase()}/api/strategy/debates?date=${date}`)
      .then(r => r.json())
      .then(d => { setDebates(d?.data || []); setLoading(false) })
      .catch(() => setLoading(false))
  }, [date])

  const parsed = useMemo(() => {
    return debates.map(d => {
      const cj = safeJsonParse(d.content_json || '{}') || {}
      const approved = cj.approved
      return {
        id: d.episode_id || d.id,
        timestamp: d.created_at,
        bull: cj.bull_case || null,
        bear: cj.bear_case || null,
        neutral: cj.neutral_case || null,
        pm: cj.recommended_action
          ? `${cj.recommended_action} (conf ${((cj.confidence || 0) * 100).toFixed(0)}%, ${approved ? 'AUTHORIZED' : 'BLOCKED'})`
          : null,
        summary: d.summary || null,
        confidence: cj.confidence,
      }
    })
  }, [debates])

  const today = new Date().toISOString().slice(0, 10)
  const latest = parsed[0]

  if (loading) return <div className="py-8"><LoadingSpinner label="Loading debates..." /></div>

  return (
    <div className="space-y-4">
      {/* Date selector */}
      <div className="flex items-center justify-between">
        <span className="font-mono text-[9px] uppercase tracking-[0.2em] text-[rgb(var(--muted))]">COMMITTEE DEBATE</span>
        <input type="date" value={date === 'today' ? today : date} onChange={e => setDate(e.target.value)}
          className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.3)] px-3 py-1.5 font-mono text-[10px] text-[rgb(var(--text))] focus:border-[rgba(var(--accent),0.5)] focus:outline-none"
          style={{ borderRadius: '2px' }} />
      </div>

      {parsed.length === 0 ? (
        <EmptyState icon={Lightbulb} title="NO DEBATES" description="Trigger AI review from Portfolio page" />
      ) : (
        <>
          {/* Latest debate -- hero split view 5:2:5 */}
          {latest && (
            <div className="grid grid-cols-1 gap-0 lg:grid-cols-12">
              {/* Bull thesis */}
              <div className="lg:col-span-5 border border-[rgba(var(--grid),0.2)] p-5"
                   style={{ borderRadius: '4px 0 0 4px', borderLeft: '3px solid rgb(var(--up))' }}>
                <div className="flex items-center gap-2 mb-3">
                  <span className="h-3 w-3 rounded-full bg-[rgb(var(--up))]" style={{ boxShadow: '0 0 6px rgba(var(--up),0.4)' }} />
                  <span className="font-mono text-xs font-black uppercase tracking-widest text-[rgb(var(--up))]">BULL THESIS</span>
                </div>
                <div className="font-mono text-[12px] leading-relaxed text-[rgb(var(--text))]">
                  {latest.bull || <span className="text-[rgb(var(--muted))] italic">(no data)</span>}
                </div>
              </div>

              {/* Arbiter verdict -- center column */}
              <div className="lg:col-span-2 border-y border-[rgba(var(--grid),0.2)] bg-[rgba(var(--surface),0.5)] flex flex-col items-center justify-center px-4 py-5">
                <div className="font-mono text-[9px] uppercase tracking-[0.2em] text-[rgb(var(--muted))] mb-3">VERDICT</div>
                {/* Confidence bar -- vertical */}
                <div className="relative w-4 h-24 border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.3)] overflow-hidden" style={{ borderRadius: '2px' }}>
                  <div className="absolute bottom-0 left-0 right-0 transition-all"
                    style={{
                      height: `${Math.round((latest.confidence || 0) * 100)}%`,
                      backgroundColor: latest.confidence >= 0.6 ? 'rgb(var(--up))' : latest.confidence >= 0.4 ? 'rgb(var(--warn))' : 'rgb(var(--danger))',
                      boxShadow: `0 0 8px ${latest.confidence >= 0.6 ? 'rgba(var(--up),0.3)' : 'rgba(var(--warn),0.3)'}`,
                    }}
                  />
                </div>
                <div className="mt-2 font-mono text-sm font-black tabular-nums text-[rgb(var(--text))]">
                  {Math.round((latest.confidence || 0) * 100)}%
                </div>
                <div className="mt-3 font-mono text-[10px] font-bold text-center text-[rgb(var(--info))] leading-tight">
                  {latest.pm || '-'}
                </div>
              </div>

              {/* Bear thesis */}
              <div className="lg:col-span-5 border border-[rgba(var(--grid),0.2)] p-5"
                   style={{ borderRadius: '0 4px 4px 0', borderRight: '3px solid rgb(var(--danger))' }}>
                <div className="flex items-center gap-2 mb-3">
                  <span className="h-3 w-3 rounded-full bg-[rgb(var(--danger))]" style={{ boxShadow: '0 0 6px rgba(var(--danger),0.4)' }} />
                  <span className="font-mono text-xs font-black uppercase tracking-widest text-[rgb(var(--danger))]">BEAR THESIS</span>
                </div>
                <div className="font-mono text-[12px] leading-relaxed text-[rgb(var(--text))]">
                  {latest.bear || <span className="text-[rgb(var(--muted))] italic">(no data)</span>}
                </div>
              </div>
            </div>
          )}

          {/* Earlier debates as chat bubbles */}
          {parsed.length > 1 && (
            <div className="space-y-3">
              <div className="font-mono text-[9px] uppercase tracking-[0.2em] text-[rgb(var(--muted))]">EARLIER DEBATES</div>
              {parsed.slice(1).map((d, i) => (
                <div key={d.id || i} className="space-y-2">
                  {d.summary && (
                    <div className="font-mono text-[10px] text-[rgb(var(--muted))]">{formatUnixSec(d.timestamp)}</div>
                  )}
                  <div className="flex gap-3">
                    {/* Bull bubble */}
                    <div className="flex-1 border-l-2 border-l-[rgb(var(--up))] bg-[rgba(var(--up),0.03)] px-3 py-2" style={{ borderRadius: '2px' }}>
                      <div className="font-mono text-[9px] font-bold text-[rgb(var(--up))] mb-1">BULL</div>
                      <div className="font-mono text-[10px] text-[rgb(var(--text))] line-clamp-2">{d.bull || '(no data)'}</div>
                    </div>
                    {/* Bear bubble */}
                    <div className="flex-1 border-l-2 border-l-[rgb(var(--danger))] bg-[rgba(var(--danger),0.03)] px-3 py-2" style={{ borderRadius: '2px' }}>
                      <div className="font-mono text-[9px] font-bold text-[rgb(var(--danger))] mb-1">BEAR</div>
                      <div className="font-mono text-[10px] text-[rgb(var(--text))] line-clamp-2">{d.bear || '(no data)'}</div>
                    </div>
                  </div>
                  {d.pm && (
                    <div className="border-l-2 border-l-[rgb(var(--info))] bg-[rgba(var(--info),0.03)] px-3 py-2 ml-8" style={{ borderRadius: '2px' }}>
                      <div className="font-mono text-[9px] font-bold text-[rgb(var(--info))] mb-1">PM VERDICT</div>
                      <div className="font-mono text-[10px] font-bold text-[rgb(var(--text))]">{d.pm}</div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

/* ── PM LLM Trace -- terminal-style collapsible ──────────── */
function PmTraceTerminal() {
  const [traces, setTraces] = useState([])
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState({})

  function reload() {
    setLoading(true)
    authFetch(`${getApiBase()}/api/strategy/pm-traces?limit=5`)
      .then(r => r.json())
      .then(d => { setTraces(d?.data || []); setLoading(false) })
      .catch(() => setLoading(false))
  }

  useEffect(() => { reload() }, [])

  function toggle(id, field) {
    setExpanded(prev => ({ ...prev, [id]: prev[id] === field ? null : field }))
  }

  return (
    <div className="border border-[rgba(var(--grid),0.3)] bg-[rgb(var(--bg))] overflow-hidden" style={{ borderRadius: '4px' }}>
      {/* Terminal title bar */}
      <div className="flex items-center justify-between bg-[rgba(var(--surface),0.6)] px-4 py-2.5 border-b border-[rgba(var(--grid),0.3)]">
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full bg-[rgb(var(--danger))]" />
          <span className="h-2.5 w-2.5 rounded-full bg-[rgb(var(--warn))]" />
          <span className="h-2.5 w-2.5 rounded-full bg-[rgb(var(--up))]" />
          <span className="ml-2 font-mono text-[10px] font-bold uppercase tracking-widest text-[rgb(var(--muted))]">PM AUDIT TRACES</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] tabular-nums text-[rgb(var(--muted))]">{traces.length} RECORDS</span>
          <button onClick={reload} disabled={loading}
            className="font-mono text-[10px] text-[rgb(var(--accent))] hover:underline disabled:opacity-50"
          >{loading ? '...' : 'REFRESH'}</button>
        </div>
      </div>

      <div className="p-3 space-y-1 max-h-[50vh] overflow-y-auto">
        {loading ? (
          <div className="py-6"><LoadingSpinner label="Loading traces..." /></div>
        ) : traces.length === 0 ? (
          <div className="py-6 text-center font-mono text-[10px] text-[rgb(var(--muted))]">$ no traces found</div>
        ) : (
          traces.map(t => (
            <div key={t.trace_id} className="font-mono text-[11px]">
              <div className="flex flex-wrap items-center gap-3 px-3 py-1.5 text-[rgb(var(--muted))] hover:bg-[rgba(var(--surface),0.3)]">
                <span className="text-[rgb(var(--up))]">$</span>
                <span className="text-[rgb(var(--text))]">{t.trace_id}</span>
                <span>{formatUnixSec(t.created_at)}</span>
                <span className="text-[rgb(var(--info))]">{t.model}</span>
                {t.latency_ms != null && <span>{t.latency_ms}ms</span>}
                <span className="ml-auto flex gap-2">
                  <button onClick={() => toggle(t.trace_id, 'prompt')}
                    className={`text-[rgb(var(--warn))] hover:underline ${expanded[t.trace_id] === 'prompt' ? 'font-bold' : ''}`}
                  >[prompt]</button>
                  <button onClick={() => toggle(t.trace_id, 'response')}
                    className={`text-[rgb(var(--up))] hover:underline ${expanded[t.trace_id] === 'response' ? 'font-bold' : ''}`}
                  >[response]</button>
                </span>
              </div>
              {expanded[t.trace_id] === 'prompt' && (
                <pre className="mx-3 mb-2 max-h-[40vh] overflow-auto bg-[rgba(var(--surface),0.2)] p-3 text-[11px] leading-relaxed text-[rgb(var(--warn))] whitespace-pre-wrap break-words border-l-2 border-l-[rgb(var(--warn))]">
                  {t.prompt || '(empty)'}
                </pre>
              )}
              {expanded[t.trace_id] === 'response' && (
                <pre className="mx-3 mb-2 max-h-[40vh] overflow-auto bg-[rgba(var(--surface),0.2)] p-3 text-[11px] leading-relaxed text-[rgb(var(--up))] whitespace-pre-wrap break-words border-l-2 border-l-[rgb(var(--up))]">
                  {t.response || '(empty)'}
                </pre>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  )
}

/* ── JSON display box ───────────────────────────────────── */
function JsonBox({ value }) {
  const text = useMemo(() => {
    if (value == null) return ''
    if (typeof value === 'string') {
      const j = safeJsonParse(value)
      if (j) return JSON.stringify(j, null, 2)
      return value
    }
    return JSON.stringify(value, null, 2)
  }, [value])
  if (!text) return <div className="font-mono text-xs text-[rgb(var(--muted))]">(empty)</div>
  return (
    <pre className="max-h-[35vh] sm:max-h-[55vh] overflow-y-auto overflow-x-hidden border border-[rgba(var(--grid),0.15)] bg-[rgba(var(--surface),0.3)] p-3 font-mono text-[11px] text-[rgb(var(--text))] whitespace-pre-wrap break-all" style={{ borderRadius: '2px' }}>
      {text}
    </pre>
  )
}

/* ── Committee Context (for modal) ───────────────────────── */
function CommitteeContextSection({ payload }) {
  const ctx = payload?.committee_context
  if (!ctx) return null

  return (
    <div className="mt-4 space-y-3">
      <div className="font-mono text-[9px] uppercase tracking-[0.2em] text-[rgb(var(--muted))]">COMMITTEE DEBATE CONTEXT</div>
      <div className="grid gap-3 lg:grid-cols-3">
        {[
          { title: 'BULL ANALYST', tone: '--up', icon: '^', content: ctx?.bull?.thesis, confidence: ctx?.bull?.confidence },
          { title: 'BEAR ANALYST', tone: '--danger', icon: 'v', content: ctx?.bear?.thesis, confidence: ctx?.bear?.confidence },
          { title: `ARBITER${ctx?.arbiter?.stance ? ` [${ctx.arbiter.stance}]` : ''}`, tone: '--info', icon: '*', content: ctx?.arbiter?.summary, confidence: payload?.confidence ?? ctx?.arbiter?.raw?.confidence },
        ].map(c => (
          <div key={c.title} className="border border-[rgba(var(--grid),0.15)] bg-[rgba(var(--surface),0.3)] p-3"
               style={{ borderRadius: '2px', borderLeft: `2px solid rgb(var(${c.tone}))` }}>
            <div className="flex items-center justify-between gap-3">
              <span className="font-mono text-[10px] font-bold uppercase tracking-widest" style={{ color: `rgb(var(${c.tone}))` }}>{c.icon} {c.title}</span>
              {c.confidence != null && <span className="font-mono text-[10px] text-[rgb(var(--muted))]">CONF {Math.round(Number(c.confidence) * 100)}%</span>}
            </div>
            <div className="mt-2 whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-[rgb(var(--text))]">{c.content || '(empty)'}</div>
          </div>
        ))}
      </div>
      {ctx?.arbiter?.decision_basis && (
        <div className="space-y-2">
          {[['BULL POINTS', ctx.arbiter.decision_basis.bull_points], ['BEAR POINTS', ctx.arbiter.decision_basis.bear_points], ['KEY TRADEOFFS', ctx.arbiter.decision_basis.key_tradeoffs], ['DATA GAPS', ctx.arbiter.decision_basis.data_gaps]].map(([label, items]) => (
            <div key={label} className="border border-[rgba(var(--grid),0.15)] bg-[rgba(var(--surface),0.2)] p-3" style={{ borderRadius: '2px' }}>
              <div className="font-mono text-[9px] font-bold uppercase tracking-widest text-[rgb(var(--muted))]">{label}</div>
              {Array.isArray(items) && items.length > 0 ? (
                <ul className="mt-2 space-y-1 font-mono text-[11px] text-[rgb(var(--text))]">
                  {items.map((item, idx) => <li key={idx}>- {item}</li>)}
                </ul>
              ) : <div className="mt-2 font-mono text-[11px] text-[rgb(var(--muted))]">(no data)</div>}
            </div>
          ))}
        </div>
      )}
      {ctx?.market_data && (
        <div className="border border-[rgba(var(--grid),0.15)] bg-[rgba(var(--surface),0.2)] p-3" style={{ borderRadius: '2px' }}>
          <div className="font-mono text-[9px] font-bold uppercase tracking-widest text-[rgb(var(--muted))]">COMMITTEE INPUT DATA</div>
          <pre className="mt-2 max-h-[24vh] overflow-auto whitespace-pre-wrap break-all font-mono text-[10px] leading-relaxed text-[rgb(var(--muted))]">{ctx.market_data}</pre>
        </div>
      )}
    </div>
  )
}

/* ── Duplicate Alerts ─────────────────────────────────────── */
function DuplicateAlertsSection({ payload }) {
  const alerts = Array.isArray(payload?.duplicate_alerts) ? payload.duplicate_alerts : []
  if (alerts.length === 0) return null
  return (
    <div className="mt-4 border-l-2 border-l-[rgb(var(--warn))] bg-[rgba(var(--warn),0.05)] p-4" style={{ borderRadius: '2px' }}>
      <div className="font-mono text-[10px] font-bold uppercase tracking-widest text-[rgb(var(--warn))]">DUPLICATE ALERTS</div>
      <div className="mt-3 space-y-2">
        {alerts.map((alert, idx) => (
          <div key={`${alert?.duplicate_of || 'dup'}-${idx}`} className="border border-[rgba(var(--warn),0.2)] bg-[rgba(var(--surface),0.3)] p-3 font-mono text-[11px]" style={{ borderRadius: '2px' }}>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-[rgb(var(--warn))]">
              <span>DUP_OF: {alert?.duplicate_of || '-'}</span>
              <span>SIM: {alert?.similarity ?? '-'}</span>
              <span>LOOKBACK: {alert?.lookback_hours ?? '-'}h</span>
            </div>
            {alert?.proposed_value && <div className="mt-2 break-words text-[rgb(var(--text))]">{alert.proposed_value}</div>}
            {alert?.supporting_evidence && <div className="mt-1 break-words text-[rgb(var(--muted))]">{alert.supporting_evidence}</div>}
          </div>
        ))}
      </div>
    </div>
  )
}

function DuplicateAlertFeed({ logs }) {
  const alerts = useMemo(() => {
    return (logs || [])
      .map(log => {
        const response = safeJsonParse(log?.response || '{}') || {}
        const alert = response?.duplicate_alert
        if (!alert || alert?.action !== 'suppressed') return null
        return { traceId: log?.trace_id, createdAt: log?.created_at, summary: response?.summary || '', ...alert }
      })
      .filter(Boolean)
      .slice(0, 8)
  }, [logs])

  if (alerts.length === 0) return null

  return (
    <div className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.4)]" style={{ borderRadius: '4px' }}>
      <div className="flex items-center justify-between border-b border-[rgba(var(--grid),0.3)] px-4 py-2.5">
        <span className="font-mono text-[10px] font-semibold uppercase tracking-widest text-[rgb(var(--warn))]">DUPLICATE SUPPRESSION FEED</span>
        <span className="font-mono text-[10px] text-[rgb(var(--muted))]">{alerts.length} SUPPRESSED</span>
      </div>
      <div className="p-3 space-y-2">
        {alerts.map(alert => (
          <div key={alert.traceId || `${alert.duplicate_of}-${alert.createdAt}`}
            className="border-l-2 border-l-[rgb(var(--warn))] bg-[rgba(var(--surface),0.3)] p-3" style={{ borderRadius: '2px' }}>
            <div className="flex flex-wrap items-center gap-3 font-mono text-[10px] text-[rgb(var(--muted))]">
              <span>{formatUnixSec(alert.createdAt) || '-'}</span>
              <span className="text-[rgb(var(--warn))]">SIM {alert.similarity ?? '-'}</span>
              <span>LOOKBACK {alert.lookback_hours ?? '-'}h</span>
            </div>
            <div className="mt-2 break-words font-mono text-[11px] font-bold text-[rgb(var(--text))]">{alert.proposed_value || '(no summary)'}</div>
            {alert.supporting_evidence && <div className="mt-1 break-words font-mono text-[10px] text-[rgb(var(--muted))]">{alert.supporting_evidence}</div>}
          </div>
        ))}
      </div>
    </div>
  )
}

/* ── Proposal Modal ──────────────────────────────────────── */
function ProposalModal({ open, onClose, proposal, onApprove, onReject, busy }) {
  const payload = safeJsonParse(proposal?.proposal_json || '')
  const status = String(proposal?.status || '').toLowerCase()
  const isPending = status === 'pending'
  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm" onMouseDown={onClose}>
      <div className="w-full max-w-4xl overflow-y-auto overflow-x-hidden border border-[rgba(var(--grid),0.4)] bg-[rgb(var(--bg))] p-5 shadow-2xl max-h-[90dvh]"
        onMouseDown={e => e.stopPropagation()} style={{ borderRadius: '4px' }}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="font-mono text-sm font-bold text-[rgb(var(--text))]">PROPOSAL DETAIL</div>
            <div className="mt-1 font-mono text-[10px] text-[rgb(var(--muted))]">
              ID: {proposal?.proposal_id || '-'} -- {formatUnixSec(proposal?.created_at) || '-'} -- <StatusTag status={proposal?.status} />
            </div>
          </div>
          <button onClick={onClose} className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.3)] px-3 py-1.5 font-mono text-xs text-[rgb(var(--text))]" style={{ borderRadius: '3px' }}>CLOSE</button>
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <div className="space-y-2">
            <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">METADATA</div>
            <div className="border border-[rgba(var(--grid),0.15)] bg-[rgba(var(--surface),0.3)] p-3 font-mono text-[11px]" style={{ borderRadius: '2px' }}>
              <div className="grid grid-cols-3 gap-2">
                {[['GENERATED_BY', proposal?.generated_by], ['TARGET_RULE', proposal?.target_rule], ['RULE_CAT', proposal?.rule_category], ['CONFIDENCE', proposal?.confidence], ['DECIDED_AT', formatUnixSec(proposal?.decided_at)]].map(([k, v]) => (
                  <Fragment key={k}>
                    <div className="text-[rgb(var(--muted))]">{k}</div>
                    <div className="col-span-2 break-words text-[rgb(var(--text))]">{v || '-'}</div>
                  </Fragment>
                ))}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button disabled={busy || !isPending} onClick={onApprove}
                className="border-2 border-[rgb(var(--up))] bg-[rgba(var(--up),0.1)] px-4 py-2 font-mono text-xs font-bold text-[rgb(var(--up))] disabled:opacity-40" style={{ borderRadius: '3px' }}>APPROVE</button>
              <button disabled={busy || !isPending} onClick={onReject}
                className="border-2 border-[rgb(var(--danger))] bg-[rgba(var(--danger),0.1)] px-4 py-2 font-mono text-xs font-bold text-[rgb(var(--danger))] disabled:opacity-40" style={{ borderRadius: '3px' }}>REJECT</button>
              {!isPending && <div className="font-mono text-[10px] text-[rgb(var(--muted))]">ONLY PENDING CAN BE ACTIONED</div>}
            </div>
          </div>
          <div className="space-y-2">
            <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">PROPOSAL_JSON</div>
            <JsonBox value={payload || proposal?.proposal_json} />
          </div>
        </div>
        <CommitteeContextSection payload={payload} />
        <DuplicateAlertsSection payload={payload} />
      </div>
    </div>
  )
}

/* ── Semantic Memory ─────────────────────────────────────── */
function SemanticMemoryTable({ data }) {
  if (!data || data.length === 0) return <div className="font-mono text-xs text-[rgb(var(--muted))] py-4">(No learned rules)</div>
  return (
    <div className="overflow-auto border border-[rgba(var(--grid),0.15)]" style={{ borderRadius: '2px' }}>
      <table className="w-full text-left font-mono text-[11px]" style={{ borderCollapse: 'collapse' }}>
        <thead>
          <tr className="border-b border-[rgba(var(--grid),0.15)]">
            <th className="px-3 py-2 text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">CONF</th>
            <th className="px-3 py-2 text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">RULE KEY</th>
            <th className="px-3 py-2 text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">CONTENT</th>
            <th className="px-3 py-2 text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">UPDATED</th>
          </tr>
        </thead>
        <tbody>
          {data.map((m, idx) => (
            <tr key={m.sm_id || m.rule_key || idx} className="border-b border-[rgba(var(--grid),0.08)] hover:bg-[rgba(var(--surface),0.3)]">
              <td className="px-3 py-2 tabular-nums text-[rgb(var(--text))]">{((m.confidence || 0) * 100).toFixed(0)}%</td>
              <td className="px-3 py-2 text-[rgb(var(--accent))]">{m.rule_key || m.sm_id}</td>
              <td className="px-3 py-2 break-words text-[rgb(var(--muted))]">{m.statement || m.content_summary || ''}</td>
              <td className="px-3 py-2 text-[rgb(var(--muted))]">{formatUnixSec(m.updated_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════
   MAIN PAGE
   ══════════════════════════════════════════════════════════════ */
export default function StrategyPage() {
  const { proposals, logs, marketRating, semanticMemory, debates, error, loading, act, batchAct, refreshProposals, refreshLogs, refreshSemanticMemory } = useStrategyData({ pollMs: 10000 })
  const STREAM_BASE = useStreamApiBase()
  const symbolNames = useSymbolNames()

  const toast = useToast()
  const [selected, setSelected] = useState(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [pendingAct, setPendingAct] = useState(null)
  const [copiedId, setCopiedId] = useState(null)
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [batchPending, setBatchPending] = useState(null)
  const [expandedProposal, setExpandedProposal] = useState(null)

  const [memOrder, setMemOrder] = useState('desc')
  const [currentPage, setCurrentPage] = useState(1)
  const PAGE_SIZE = 50

  // SSE
  useEffect(() => {
    const token = getToken()
    const url = `${STREAM_BASE}/logs${token ? `?token=${token}` : ''}`
    const es = new EventSource(url)
    let t = null
    const scheduleRefresh = () => {
      if (t) clearTimeout(t)
      t = setTimeout(() => { refreshProposals(); refreshLogs() }, 500)
    }
    es.addEventListener('log', scheduleRefresh)
    es.addEventListener('error', () => {})
    return () => { if (t) clearTimeout(t); es.close() }
  }, [STREAM_BASE, refreshProposals, refreshLogs])

  useEffect(() => {
    if (refreshSemanticMemory) refreshSemanticMemory({ sort: 'confidence', order: memOrder, limit: 50 })
  }, [memOrder, refreshSemanticMemory])

  const rows = useMemo(() => {
    return (proposals || []).map(p => {
      const payload = safeJsonParse(p?.proposal_json || '') || {}
      const symbol = payload?.symbol || payload?.ticker || payload?.stock || payload?.contract || ''
      const side = payload?.side || payload?.direction || payload?.action || ''
      return { ...p, _symbol: symbol ? formatSymbol(symbol, symbolNames) : '-', _side: side || '-', _ts: formatUnixSec(p?.created_at) || '-' }
    })
  }, [proposals, symbolNames])

  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE))
  const pagedRows = useMemo(() => {
    const start = (currentPage - 1) * PAGE_SIZE
    return rows.slice(start, start + PAGE_SIZE)
  }, [rows, currentPage])

  useEffect(() => {
    setCurrentPage(p => {
      const maxPage = Math.max(1, Math.ceil((proposals || []).length / PAGE_SIZE))
      return p > maxPage ? 1 : p
    })
  }, [proposals])

  const openDetail = p => { setSelected(p); setModalOpen(true) }
  const closeDetail = () => { setModalOpen(false) }
  const doApprove = (p) => { if (p?.proposal_id) setPendingAct({ type: 'approve', proposal: p }) }
  const doReject = (p) => { if (p?.proposal_id) setPendingAct({ type: 'reject', proposal: p }) }

  const confirmAct = async () => {
    if (!pendingAct) return
    const { type, proposal: p } = pendingAct
    setPendingAct(null); setModalOpen(false)
    try {
      await act(type, p.proposal_id, { actor: 'operator', reason: `manual ${type} via UI` })
      toast.success(type === 'approve' ? `Proposal ${p.proposal_id} approved` : `Proposal ${p.proposal_id} rejected`)
    } catch (e) { toast.error(`Action failed: ${e?.message || e}`) }
  }

  const pendingRows = useMemo(() => pagedRows.filter(r => String(r?.status || '').toLowerCase() === 'pending'), [pagedRows])
  const allPendingSelected = pendingRows.length > 0 && pendingRows.every(r => selectedIds.has(r.proposal_id))

  const toggleSelect = (pid) => {
    setSelectedIds(prev => { const next = new Set(prev); next.has(pid) ? next.delete(pid) : next.add(pid); return next })
  }
  const toggleSelectAll = () => {
    if (allPendingSelected) setSelectedIds(new Set())
    else setSelectedIds(new Set(pendingRows.map(r => r.proposal_id)))
  }
  const confirmBatch = async () => {
    if (!batchPending) return
    const ids = [...selectedIds]; const action = batchPending.type
    setBatchPending(null)
    try {
      const result = await batchAct(action, ids, { actor: 'operator', reason: `batch ${action} via UI` })
      if (result) {
        toast.success(`Batch ${action} ${result.succeeded?.length || 0} done`)
        if (result.failed?.length) toast.warning(`${result.failed.length} skipped`)
      }
    } catch (e) { toast.error(`Batch failed: ${e?.message || e}`) }
    setSelectedIds(new Set())
  }

  useEffect(() => {
    setSelectedIds(prev => {
      if (prev.size === 0) return prev
      const validIds = new Set((proposals || []).filter(p => p.status === 'pending').map(p => p.proposal_id))
      const next = new Set([...prev].filter(id => validIds.has(id)))
      return next.size === prev.size ? prev : next
    })
  }, [proposals])

  function copyId(id) {
    navigator.clipboard.writeText(id).then(() => { setCopiedId(id); setTimeout(() => setCopiedId(null), 2000) })
  }

  // Find most recent pending or approved proposal for hero
  const heroProposal = useMemo(() => {
    return rows.find(r => r.status === 'pending') || rows[0]
  }, [rows])

  return (
    <div className="space-y-6 pb-20 lg:pb-4">

      {/* ══════════════════════════════════════════════════════════
          HERO: Rating + Active Proposal (side by side)
          ══════════════════════════════════════════════════════════ */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <div className="lg:col-span-4">
          <RatingHero rating={marketRating?.rating} basis={marketRating?.basis} />
        </div>
        <div className="lg:col-span-8">
          {heroProposal ? (
            <div className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.4)] p-5" style={{ borderRadius: '4px' }}>
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-3">
                  <span className="font-mono text-[9px] uppercase tracking-[0.2em] text-[rgb(var(--muted))]">ACTIVE PROPOSAL</span>
                  <StatusTag status={heroProposal.status} />
                </div>
                <span className="font-mono text-[10px] tabular-nums text-[rgb(var(--muted))]">{heroProposal._ts}</span>
              </div>
              <div className="flex items-baseline gap-4">
                <span className="font-mono text-2xl font-black text-[rgb(var(--text))]">{heroProposal._symbol}</span>
                <span className={`font-mono text-sm font-bold uppercase ${
                  heroProposal._side.toLowerCase() === 'buy' ? 'text-[rgb(var(--up))]' : heroProposal._side.toLowerCase() === 'sell' ? 'text-[rgb(var(--danger))]' : 'text-[rgb(var(--text))]'
                }`}>{heroProposal._side}</span>
                {heroProposal.confidence != null && (
                  <span className="font-mono text-xs tabular-nums text-[rgb(var(--muted))]">CONF {heroProposal.confidence}</span>
                )}
              </div>
              <div className="mt-3 flex gap-2">
                <button onClick={() => openDetail(heroProposal)}
                  className="border border-[rgba(var(--accent),0.4)] bg-[rgba(var(--accent),0.08)] px-4 py-2 font-mono text-[10px] font-bold text-[rgb(var(--accent))]"
                  style={{ borderRadius: '3px' }}
                >VIEW DETAIL</button>
                {String(heroProposal.status).toLowerCase() === 'pending' && (
                  <>
                    <button onClick={() => doApprove(heroProposal)} disabled={loading.act}
                      className="border border-[rgb(var(--up))] bg-[rgba(var(--up),0.1)] px-4 py-2 font-mono text-[10px] font-bold text-[rgb(var(--up))] disabled:opacity-40"
                      style={{ borderRadius: '3px' }}
                    >APPROVE</button>
                    <button onClick={() => doReject(heroProposal)} disabled={loading.act}
                      className="border border-[rgb(var(--danger))] bg-[rgba(var(--danger),0.1)] px-4 py-2 font-mono text-[10px] font-bold text-[rgb(var(--danger))] disabled:opacity-40"
                      style={{ borderRadius: '3px' }}
                    >REJECT</button>
                  </>
                )}
              </div>
            </div>
          ) : (
            <div className="border border-[rgba(var(--grid),0.2)] bg-[rgba(var(--surface),0.15)] p-8" style={{ borderRadius: '4px' }}>
              <EmptyState icon={Target} title="NO PROPOSALS" description="System will generate proposals on next trading session" />
            </div>
          )}
        </div>
      </div>

      {/* ══════════════════════════════════════════════════════════
          BULL vs BEAR DEBATE -- split view
          ══════════════════════════════════════════════════════════ */}
      <DebateHeroSection />

      {/* ══════════════════════════════════════════════════════════
          PROPOSAL QUEUE -- compact rows with status dots
          ══════════════════════════════════════════════════════════ */}
      <div className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.4)]" style={{ borderRadius: '4px' }}>
        <div className="flex items-center justify-between border-b border-[rgba(var(--grid),0.3)] px-4 py-2.5">
          <span className="font-mono text-[10px] font-semibold uppercase tracking-widest text-[rgb(var(--text))]">PROPOSAL QUEUE</span>
          <span className="font-mono text-[10px] text-[rgb(var(--muted))]">{rows.length} TOTAL</span>
        </div>

        {error && <div className="mx-4 mt-3 border-l-2 border-l-[rgb(var(--danger))] bg-[rgba(var(--danger),0.05)] p-3 font-mono text-xs text-[rgb(var(--danger))]">{error}</div>}

        {/* Batch bar */}
        {selectedIds.size > 0 && (
          <div className="mx-4 mt-3 flex items-center gap-3 border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.4)] px-4 py-2.5" style={{ borderRadius: '3px' }}>
            <span className="font-mono text-xs text-[rgb(var(--text))]">SELECTED: <span className="font-bold">{selectedIds.size}</span></span>
            <button disabled={loading.act} onClick={() => setBatchPending({ type: 'approve' })}
              className="border border-[rgb(var(--up))] bg-[rgba(var(--up),0.1)] px-3 py-1.5 font-mono text-[10px] font-bold text-[rgb(var(--up))] disabled:opacity-40" style={{ borderRadius: '3px' }}>BATCH APPROVE</button>
            <button disabled={loading.act} onClick={() => setBatchPending({ type: 'reject' })}
              className="border border-[rgb(var(--danger))] bg-[rgba(var(--danger),0.1)] px-3 py-1.5 font-mono text-[10px] font-bold text-[rgb(var(--danger))] disabled:opacity-40" style={{ borderRadius: '3px' }}>BATCH REJECT</button>
            <button onClick={() => setSelectedIds(new Set())} className="ml-auto font-mono text-[10px] text-[rgb(var(--muted))] hover:text-[rgb(var(--text))]">CANCEL</button>
          </div>
        )}

        {/* Compact proposal rows */}
        <div className="p-3 space-y-1">
          {pagedRows.length === 0 ? (
            <div className="py-8">
              {loading.proposals ? <LoadingSpinner label="Loading proposals..." /> : <EmptyState icon={Target} title="NO PROPOSALS" description="System will generate proposals on next trading session" />}
            </div>
          ) : (
            pagedRows.map(p => {
              const canAct = String(p?.status || '').toLowerCase() === 'pending'
              const isExpanded = expandedProposal === p.proposal_id
              return (
                <div key={p.proposal_id}>
                  <div className="flex items-center gap-3 px-3 py-2.5 hover:bg-[rgba(var(--surface),0.3)] transition-colors cursor-pointer"
                       style={{ borderRadius: '2px' }}
                       onClick={() => setExpandedProposal(isExpanded ? null : p.proposal_id)}>
                    {canAct && (
                      <input type="checkbox" checked={selectedIds.has(p.proposal_id)}
                        onChange={e => { e.stopPropagation(); toggleSelect(p.proposal_id) }}
                        onClick={e => e.stopPropagation()}
                        className="accent-[rgb(var(--accent))] h-3.5 w-3.5" />
                    )}
                    <StatusTag status={p.status} />
                    <span className="font-mono text-xs font-bold text-[rgb(var(--text))] min-w-[4rem]">{p._symbol}</span>
                    <span className={`font-mono text-[10px] font-bold ${
                      p._side.toLowerCase() === 'buy' ? 'text-[rgb(var(--up))]' : p._side.toLowerCase() === 'sell' ? 'text-[rgb(var(--danger))]' : 'text-[rgb(var(--muted))]'
                    }`}>{p._side}</span>
                    <span className="font-mono text-[10px] tabular-nums text-[rgb(var(--muted))] hidden sm:inline">{p._ts}</span>
                    <span className="ml-auto flex items-center gap-2">
                      {p.confidence != null && <span className="font-mono text-[10px] tabular-nums text-[rgb(var(--muted))]">{p.confidence}</span>}
                      <button onClick={e => { e.stopPropagation(); copyId(p.proposal_id) }} className="text-[rgb(var(--muted))] hover:text-[rgb(var(--text))]">
                        {copiedId === p.proposal_id ? <Check className="h-3 w-3 text-[rgb(var(--up))]" /> : <Copy className="h-3 w-3" />}
                      </button>
                      {isExpanded ? <ChevronDown className="h-3.5 w-3.5 text-[rgb(var(--muted))]" /> : <ChevronRight className="h-3.5 w-3.5 text-[rgb(var(--muted))]" />}
                    </span>
                  </div>
                  {isExpanded && (
                    <div className="ml-8 mb-2 border-l-2 border-l-[rgba(var(--accent),0.3)] pl-4 py-2 space-y-2">
                      <div className="font-mono text-[10px] text-[rgb(var(--muted))]">ID: {p.proposal_id}</div>
                      <div className="flex gap-2">
                        <button onClick={() => openDetail(p)}
                          className="border border-[rgba(var(--accent),0.4)] bg-[rgba(var(--accent),0.08)] px-3 py-1.5 font-mono text-[10px] font-bold text-[rgb(var(--accent))]" style={{ borderRadius: '3px' }}>VIEW FULL</button>
                        {canAct && (
                          <>
                            <button disabled={loading.act} onClick={() => doApprove(p)}
                              className="border border-[rgb(var(--up))] bg-[rgba(var(--up),0.1)] px-2.5 py-1.5 font-mono text-[10px] font-bold text-[rgb(var(--up))] disabled:opacity-40" style={{ borderRadius: '3px' }}>APPROVE</button>
                            <button disabled={loading.act} onClick={() => doReject(p)}
                              className="border border-[rgb(var(--danger))] bg-[rgba(var(--danger),0.1)] px-2.5 py-1.5 font-mono text-[10px] font-bold text-[rgb(var(--danger))] disabled:opacity-40" style={{ borderRadius: '3px' }}>REJECT</button>
                          </>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )
            })
          )}
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between border-t border-[rgba(var(--grid),0.2)] px-4 py-2.5">
            <div className="font-mono text-[10px] text-[rgb(var(--muted))]">{rows.length} TOTAL / PAGE {currentPage}/{totalPages}</div>
            <div className="flex items-center gap-1.5">
              <button disabled={currentPage <= 1} onClick={() => setCurrentPage(1)}
                className="border border-[rgba(var(--grid),0.3)] px-2 py-1 font-mono text-[10px] text-[rgb(var(--muted))] disabled:opacity-30" style={{ borderRadius: '2px' }}>{'<<'}</button>
              <button disabled={currentPage <= 1} onClick={() => setCurrentPage(p => p - 1)}
                className="border border-[rgba(var(--grid),0.3)] px-2 py-1 font-mono text-[10px] text-[rgb(var(--muted))] disabled:opacity-30" style={{ borderRadius: '2px' }}>{'<'}</button>
              {Array.from({ length: Math.min(totalPages, 5) }, (_, i) => {
                let page
                if (totalPages <= 5) page = i + 1
                else if (currentPage <= 3) page = i + 1
                else if (currentPage >= totalPages - 2) page = totalPages - 4 + i
                else page = currentPage - 2 + i
                return (
                  <button key={page} onClick={() => setCurrentPage(page)}
                    className={`px-2.5 py-1 font-mono text-[10px] font-bold ${page === currentPage ? 'bg-[rgba(var(--accent),0.2)] text-[rgb(var(--accent))]' : 'border border-[rgba(var(--grid),0.3)] text-[rgb(var(--muted))]'}`}
                    style={{ borderRadius: '2px' }}>{page}</button>
                )
              })}
              <button disabled={currentPage >= totalPages} onClick={() => setCurrentPage(p => p + 1)}
                className="border border-[rgba(var(--grid),0.3)] px-2 py-1 font-mono text-[10px] text-[rgb(var(--muted))] disabled:opacity-30" style={{ borderRadius: '2px' }}>{'>'}</button>
              <button disabled={currentPage >= totalPages} onClick={() => setCurrentPage(totalPages)}
                className="border border-[rgba(var(--grid),0.3)] px-2 py-1 font-mono text-[10px] text-[rgb(var(--muted))] disabled:opacity-30" style={{ borderRadius: '2px' }}>{'>>'}</button>
            </div>
          </div>
        )}

        {/* Select all */}
        {pendingRows.length > 0 && (
          <div className="flex items-center gap-2 border-t border-[rgba(var(--grid),0.15)] px-4 py-2">
            <input type="checkbox" checked={allPendingSelected} onChange={toggleSelectAll} className="accent-[rgb(var(--accent))] h-3.5 w-3.5" />
            <span className="font-mono text-[10px] text-[rgb(var(--muted))]">SELECT ALL PENDING ({pendingRows.length})</span>
          </div>
        )}
      </div>

      {/* ══════════════════════════════════════════════════════════
          SEMANTIC MEMORY (full width)
          ══════════════════════════════════════════════════════════ */}
      <div className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.4)]" style={{ borderRadius: '4px' }}>
        <div className="flex items-center justify-between border-b border-[rgba(var(--grid),0.3)] px-4 py-2.5">
          <span className="font-mono text-[10px] font-semibold uppercase tracking-widest text-[rgb(var(--text))]">SEMANTIC MEMORY</span>
          <button onClick={() => setMemOrder(o => (o === 'desc' ? 'asc' : 'desc'))}
            className="font-mono text-[10px] text-[rgb(var(--accent))] hover:underline">CONF {memOrder === 'desc' ? 'v HIGH' : '^ LOW'}</button>
        </div>
        <div className="p-4">
          <div className="mb-2 font-mono text-[10px] text-[rgb(var(--muted))]">AI-learned rules, ranked by confidence from source episodes</div>
          <SemanticMemoryTable data={semanticMemory} />
        </div>
      </div>

      {/* ══════════════════════════════════════════════════════════
          DUPLICATE FEED + LLM TRACES (terminal-style)
          ══════════════════════════════════════════════════════════ */}
      <DuplicateAlertFeed logs={logs} />
      <PmTraceTerminal />

      {/* ── Proposal Modal ─────────────────────────────────────── */}
      <ProposalModal open={modalOpen} onClose={closeDetail} proposal={selected} busy={loading.act} onApprove={() => doApprove(selected)} onReject={() => doReject(selected)} />

      {/* ── Batch Confirm Dialog ───────────────────────────────── */}
      {batchPending && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm" onMouseDown={() => setBatchPending(null)}>
          <div className="w-full max-w-xs border border-[rgba(var(--grid),0.4)] bg-[rgb(var(--bg))] p-5 shadow-2xl" onMouseDown={e => e.stopPropagation()} style={{ borderRadius: '4px' }}>
            <div className={`font-mono text-sm font-bold mb-2 ${batchPending.type === 'approve' ? 'text-[rgb(var(--up))]' : 'text-[rgb(var(--danger))]'}`}>BATCH {batchPending.type.toUpperCase()} {selectedIds.size} PROPOSALS</div>
            <div className="font-mono text-xs text-[rgb(var(--muted))] mb-4">This action cannot be undone.</div>
            <div className="flex gap-3">
              <button onClick={() => setBatchPending(null)} className="flex-1 border border-[rgba(var(--grid),0.3)] py-2.5 font-mono text-xs text-[rgb(var(--muted))]" style={{ borderRadius: '3px' }}>CANCEL</button>
              <button autoFocus onClick={confirmBatch}
                className={`flex-1 border-2 py-2.5 font-mono text-xs font-bold ${batchPending.type === 'approve' ? 'border-[rgb(var(--up))] bg-[rgba(var(--up),0.15)] text-[rgb(var(--up))]' : 'border-[rgb(var(--danger))] bg-[rgba(var(--danger),0.15)] text-[rgb(var(--danger))]'}`}
                style={{ borderRadius: '3px' }}>CONFIRM ({selectedIds.size})</button>
            </div>
          </div>
        </div>
      )}

      {/* ── Single Confirm Dialog ──────────────────────────────── */}
      {pendingAct && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm" onMouseDown={() => setPendingAct(null)}>
          <div className="w-full max-w-xs border border-[rgba(var(--grid),0.4)] bg-[rgb(var(--bg))] p-5 shadow-2xl" onMouseDown={e => e.stopPropagation()} style={{ borderRadius: '4px' }}>
            <div className={`font-mono text-sm font-bold mb-2 ${pendingAct.type === 'approve' ? 'text-[rgb(var(--up))]' : 'text-[rgb(var(--danger))]'}`}>CONFIRM {pendingAct.type.toUpperCase()}</div>
            <div className="font-mono text-[10px] text-[rgb(var(--muted))] mb-1">PROPOSAL ID</div>
            <div className="mb-4 border border-[rgba(var(--grid),0.15)] bg-[rgba(var(--surface),0.3)] px-3 py-2 font-mono text-xs text-[rgb(var(--text))] break-all" style={{ borderRadius: '2px' }}>{pendingAct.proposal?.proposal_id}</div>
            <div className="flex gap-3">
              <button onClick={() => setPendingAct(null)} className="flex-1 border border-[rgba(var(--grid),0.3)] py-2.5 font-mono text-xs text-[rgb(var(--muted))]" style={{ borderRadius: '3px' }}>CANCEL</button>
              <button autoFocus onClick={confirmAct}
                className={`flex-1 border-2 py-2.5 font-mono text-xs font-bold ${pendingAct.type === 'approve' ? 'border-[rgb(var(--up))] bg-[rgba(var(--up),0.15)] text-[rgb(var(--up))]' : 'border-[rgb(var(--danger))] bg-[rgba(var(--danger),0.15)] text-[rgb(var(--danger))]'}`}
                style={{ borderRadius: '3px' }}>CONFIRM</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
