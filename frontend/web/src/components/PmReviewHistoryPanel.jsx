import React, { useEffect, useState, useCallback } from 'react'
import { History, ChevronDown, ChevronRight, ShieldCheck, ShieldOff, RefreshCw } from 'lucide-react'
import { fetchPmHistory } from '../lib/pmApi'

const PAGE_SIZE = 10

export default function PmReviewHistoryPanel() {
  const [reviews, setReviews] = useState([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    const { data, pagination } = await fetchPmHistory({ limit: PAGE_SIZE, offset })
    setReviews(data)
    setTotal(pagination.total)
    setLoading(false)
  }, [offset])

  useEffect(() => { load() }, [load])

  function toggle(id) {
    setExpanded(prev => (prev === id ? null : id))
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/20 p-5 shadow-panel">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <History className="h-4 w-4 text-violet-400" />
          <span className="text-sm font-semibold text-slate-200">PM 審核歷史</span>
          <span className="text-xs text-slate-500">({total} 筆)</span>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-800 hover:text-slate-200"
          title="重新整理"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {loading && reviews.length === 0 ? (
        <div className="text-xs text-slate-500">讀取中…</div>
      ) : reviews.length === 0 ? (
        <div className="text-xs text-slate-500">尚無審核紀錄</div>
      ) : (
        <div className="space-y-2">
          {reviews.map(r => {
            const isExpanded = expanded === r.review_id
            const approved = !!r.approved
            const ts = r.reviewed_at
              ? new Date(r.reviewed_at).toLocaleString('zh-TW', { hour12: false })
              : ''
            const consensus = tryParseJson(r.consensus_points)
            const divergence = tryParseJson(r.divergence_points)

            return (
              <div
                key={r.review_id}
                className="rounded-xl border border-slate-800/60 bg-slate-900/40"
              >
                <button
                  onClick={() => toggle(r.review_id)}
                  className="flex w-full items-center gap-3 px-4 py-2.5 text-left"
                >
                  {isExpanded
                    ? <ChevronDown className="h-3.5 w-3.5 text-slate-500 flex-shrink-0" />
                    : <ChevronRight className="h-3.5 w-3.5 text-slate-500 flex-shrink-0" />}
                  {approved
                    ? <ShieldCheck className="h-4 w-4 text-emerald-400 flex-shrink-0" />
                    : <ShieldOff className="h-4 w-4 text-rose-400 flex-shrink-0" />}
                  <span className="text-xs font-medium text-slate-300">{r.review_date}</span>
                  <span className={`text-xs ${approved ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {approved ? '授權' : '封鎖'}
                  </span>
                  <span className="text-xs text-slate-500">
                    信心 {((r.confidence || 0) * 100).toFixed(0)}%
                  </span>
                  <span className="ml-auto text-xs text-slate-600">
                    {r.source === 'manual' ? '人工' : r.source === 'llm' ? 'LLM' : r.source}
                  </span>
                </button>

                {isExpanded && (
                  <div className="border-t border-slate-800/40 px-4 py-3 space-y-2">
                    {r.reason && (
                      <div className="text-xs text-slate-400">
                        <span className="text-slate-500">理由：</span>{r.reason}
                      </div>
                    )}
                    {r.recommended_action && (
                      <div className="text-xs text-slate-400">
                        <span className="text-slate-500">建議：</span>{r.recommended_action}
                      </div>
                    )}
                    {(r.bull_case || r.bear_case || r.neutral_case) && (
                      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3 pt-1">
                        {r.bull_case && (
                          <div>
                            <div className="text-xs font-medium text-emerald-400">多方</div>
                            <div className="mt-0.5 text-xs text-slate-500 line-clamp-3">{r.bull_case}</div>
                          </div>
                        )}
                        {r.bear_case && (
                          <div>
                            <div className="text-xs font-medium text-rose-400">空方</div>
                            <div className="mt-0.5 text-xs text-slate-500 line-clamp-3">{r.bear_case}</div>
                          </div>
                        )}
                        {r.neutral_case && (
                          <div>
                            <div className="text-xs font-medium text-slate-400">中立</div>
                            <div className="mt-0.5 text-xs text-slate-500 line-clamp-3">{r.neutral_case}</div>
                          </div>
                        )}
                      </div>
                    )}
                    {consensus.length > 0 && (
                      <div className="text-xs">
                        <span className="text-slate-500">共識：</span>
                        <span className="text-slate-400">{consensus.join('、')}</span>
                      </div>
                    )}
                    {divergence.length > 0 && (
                      <div className="text-xs">
                        <span className="text-slate-500">分歧：</span>
                        <span className="text-slate-400">{divergence.join('、')}</span>
                      </div>
                    )}
                    {ts && (
                      <div className="text-xs text-slate-600">審核時間：{ts}</div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Pagination */}
      {total > PAGE_SIZE && (
        <div className="mt-3 flex items-center justify-between text-xs">
          <button
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            disabled={offset === 0}
            className="rounded px-2 py-1 text-slate-400 hover:bg-slate-800 disabled:opacity-30"
          >
            ← 上一頁
          </button>
          <span className="text-slate-500">{currentPage} / {totalPages}</span>
          <button
            onClick={() => setOffset(offset + PAGE_SIZE)}
            disabled={offset + PAGE_SIZE >= total}
            className="rounded px-2 py-1 text-slate-400 hover:bg-slate-800 disabled:opacity-30"
          >
            下一頁 →
          </button>
        </div>
      )}
    </div>
  )
}

function tryParseJson(val) {
  if (Array.isArray(val)) return val
  if (typeof val === 'string') {
    try { return JSON.parse(val) } catch { return [] }
  }
  return []
}
