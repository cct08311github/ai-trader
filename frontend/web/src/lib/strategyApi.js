import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getApiBase, getToken } from './auth'

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

async function fetchJsonWithTimeout(url, options = {}, { timeoutMs = 5000 } = {}) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const res = await fetch(url, {
      ...options,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}),
        ...(options.headers || {})
      }
    })

    if (!res.ok) {
      let detail = ''
      try {
        const body = await res.json()
        detail = body?.detail ? `: ${body.detail}` : ''
      } catch {
        // ignore
      }
      throw new Error(`API error: ${res.status}${detail}`)
    }

    return await res.json()
  } catch (err) {
    if (err?.name === 'AbortError') throw new Error(`timeout (${timeoutMs}ms)`) // normalized
    throw err
  } finally {
    clearTimeout(timer)
  }
}

async function callApiWithRetry(url, options, { retries = 1, backoffMs = 400, timeoutMs = 5000 } = {}) {
  let lastErr
  for (let i = 0; i <= retries; i++) {
    try {
      return await fetchJsonWithTimeout(url, options, { timeoutMs })
    } catch (err) {
      lastErr = err
      const msg = String(err?.message || '')
      const retryable = msg.includes('timeout') || msg.includes('Failed to fetch')
      if (!retryable || i === retries) break
      await sleep(backoffMs * (i + 1))
    }
  }
  throw lastErr
}

export function useStrategyApiBase() {
  return useMemo(() => `${getApiBase()}/api/strategy`, [])
}

export function useStreamApiBase() {
  return useMemo(() => `${getApiBase()}/api/stream`, [])
}

export function createStrategyClient(API_BASE) {
  return {
    async proposals({ limit = 100, offset = 0, status, timeoutMs = 5000 } = {}) {
      const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) })
      if (status) qs.set('status', status)
      return await callApiWithRetry(`${API_BASE}/proposals?${qs.toString()}`, { method: 'GET' }, { retries: 1, timeoutMs })
    },
    async logs({ limit = 100, offset = 0, traceId, timeoutMs = 5000 } = {}) {
      const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) })
      if (traceId) qs.set('trace_id', traceId)
      return await callApiWithRetry(`${API_BASE}/logs?${qs.toString()}`, { method: 'GET' }, { retries: 1, timeoutMs })
    },
    async approve(proposalId, { actor = 'user', reason = '' } = {}) {
      return await callApiWithRetry(
        `${API_BASE}/${encodeURIComponent(proposalId)}/approve`,
        { method: 'POST', body: JSON.stringify({ actor, reason }) },
        { retries: 0, timeoutMs: 8000 }
      )
    },
    async reject(proposalId, { actor = 'user', reason = '' } = {}) {
      return await callApiWithRetry(
        `${API_BASE}/${encodeURIComponent(proposalId)}/reject`,
        { method: 'POST', body: JSON.stringify({ actor, reason }) },
        { retries: 0, timeoutMs: 8000 }
      )
    },
    async batchDecide(action, proposalIds, { actor = 'user', reason = '' } = {}) {
      return await callApiWithRetry(
        `${API_BASE}/proposals/batch/${action}`,
        { method: 'POST', body: JSON.stringify({ proposal_ids: proposalIds, actor, reason }) },
        { retries: 0, timeoutMs: 15000 }
      )
    },
    async marketRating({ timeoutMs = 5000 } = {}) {
      return await callApiWithRetry(
        `${API_BASE}/market-rating`,
        { method: 'GET' },
        { retries: 1, timeoutMs }
      )
    },
    async semanticMemory({ sort = 'confidence', order = 'desc', limit = 50, timeoutMs = 5000 } = {}) {
      const qs = new URLSearchParams({ sort: String(sort), order: String(order), limit: String(limit) })
      return await callApiWithRetry(
        `${API_BASE}/semantic-memory?${qs.toString()}`,
        { method: 'GET' },
        { retries: 1, timeoutMs }
      )
    },
    async debates({ date = 'today', timeoutMs = 5000 } = {}) {
      const qs = new URLSearchParams({ date: String(date) })
      return await callApiWithRetry(
        `${API_BASE}/debates?${qs.toString()}`,
        { method: 'GET' },
        { retries: 1, timeoutMs }
      )
    }
  }
}

export function useStrategyData({ pollMs = 8000 } = {}) {
  const API_BASE = useStrategyApiBase()

  const client = useMemo(() => createStrategyClient(API_BASE), [API_BASE])

  const [proposals, setProposals] = useState([])
  const [logs, setLogs] = useState([])
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState({ proposals: false, logs: false, act: false, marketRating: false, semanticMemory: false, debates: false })
  const [marketRating, setMarketRating] = useState(null)
  const [semanticMemory, setSemanticMemory] = useState([])
  const [debates, setDebates] = useState([])

  const mountedRef = useRef(false)

  const refreshProposals = useCallback(async () => {
    setLoading(p => ({ ...p, proposals: true }))
    try {
      const res = await client.proposals({ limit: 200 })
      if (!mountedRef.current) return
      setProposals(res?.data || [])
      setError(null)
    } catch (err) {
      if (!mountedRef.current) return
      setError(`無法取得策略提案: ${err.message}`)
    } finally {
      if (mountedRef.current) setLoading(p => ({ ...p, proposals: false }))
    }
  }, [client])

  const refreshLogs = useCallback(async () => {
    setLoading(p => ({ ...p, logs: true }))
    try {
      const res = await client.logs({ limit: 200 })
      if (!mountedRef.current) return
      setLogs(res?.data || [])
      setError(null)
    } catch (err) {
      if (!mountedRef.current) return
      setError(`無法取得決策日誌: ${err.message}`)
    } finally {
      if (mountedRef.current) setLoading(p => ({ ...p, logs: false }))
    }
  }, [client])

  const refreshMarketRating = useCallback(async () => {
    setLoading(p => ({ ...p, marketRating: true }))
    try {
      const res = await client.marketRating()
      if (!mountedRef.current) return
      setMarketRating(res?.data || null)
      setError(null)
    } catch (err) {
      if (!mountedRef.current) return
      setError(`無法取得市場評級: ${err.message}`)
    } finally {
      if (mountedRef.current) setLoading(p => ({ ...p, marketRating: false }))
    }
  }, [client])

  const refreshSemanticMemory = useCallback(async ({ sort = 'confidence', order = 'desc', limit = 50 } = {}) => {
    setLoading(p => ({ ...p, semanticMemory: true }))
    try {
      const res = await client.semanticMemory({ sort, order, limit })
      if (!mountedRef.current) return
      setSemanticMemory(res?.data || [])
      setError(null)
    } catch (err) {
      if (!mountedRef.current) return
      setError(`無法取得語義記憶: ${err.message}`)
    } finally {
      if (mountedRef.current) setLoading(p => ({ ...p, semanticMemory: false }))
    }
  }, [client])

  const refreshDebates = useCallback(async ({ date = 'today' } = {}) => {
    setLoading(p => ({ ...p, debates: true }))
    try {
      const res = await client.debates({ date })
      if (!mountedRef.current) return
      setDebates(res?.data || [])
      setError(null)
    } catch (err) {
      if (!mountedRef.current) return
      setError(`無法取得辯論記錄: ${err.message}`)
    } finally {
      if (mountedRef.current) setLoading(p => ({ ...p, debates: false }))
    }
  }, [client])

  useEffect(() => {
    mountedRef.current = true
    refreshProposals()
    refreshLogs()
    refreshMarketRating()
    refreshSemanticMemory()
    refreshDebates()
    const t = setInterval(() => {
      refreshProposals()
    }, pollMs)
    return () => {
      mountedRef.current = false
      clearInterval(t)
    }
  }, [refreshProposals, refreshLogs, refreshMarketRating, refreshSemanticMemory, refreshDebates, pollMs])

  const act = useCallback(
    async (kind, proposalId, { actor = 'user', reason = '' } = {}) => {
      setLoading(p => ({ ...p, act: true }))
      try {
        if (kind === 'approve') await client.approve(proposalId, { actor, reason })
        else if (kind === 'reject') await client.reject(proposalId, { actor, reason })
        else throw new Error('unknown action')
        await refreshProposals()
        return true
      } catch (err) {
        setError(`操作失敗: ${err.message}`)
        return false
      } finally {
        setLoading(p => ({ ...p, act: false }))
      }
    },
    [client, refreshProposals]
  )

  const batchAct = useCallback(
    async (action, proposalIds, { actor = 'user', reason = '' } = {}) => {
      setLoading(p => ({ ...p, act: true }))
      try {
        const result = await client.batchDecide(action, proposalIds, { actor, reason })
        await refreshProposals()
        return result
      } catch (err) {
        setError(`批量操作失敗: ${err.message}`)
        return null
      } finally {
        setLoading(p => ({ ...p, act: false }))
      }
    },
    [client, refreshProposals]
  )

  return {
    API_BASE,
    proposals,
    logs,
    marketRating,
    semanticMemory,
    debates,
    error,
    loading,
    refreshProposals,
    refreshLogs,
    refreshMarketRating,
    refreshSemanticMemory,
    refreshDebates,
    act,
    batchAct
  }
}
