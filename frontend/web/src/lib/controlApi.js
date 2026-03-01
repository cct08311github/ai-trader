// Shared control API client + React hook
// Used by both System page ControlPanel and GlobalControlBar

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

// Default backend: FastAPI command center (see frontend/backend)
// Override via Vite env: VITE_API_BASE=http://localhost:8080
const DEFAULT_API_BASE = ''

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
        ...(options.headers || {})
      }
    })

    if (!res.ok) {
      // Try to extract FastAPI detail for better UX
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
    if (err?.name === 'AbortError') {
      throw new Error(`timeout (${timeoutMs}ms)`) // normalized
    }
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
      // Only retry on network/timeout type errors
      const msg = String(err?.message || '')
      const retryable = msg.includes('timeout') || msg.includes('Failed to fetch')
      if (!retryable || i === retries) break
      await sleep(backoffMs * (i + 1))
    }
  }
  throw lastErr
}

export function useControlApiBase() {
  return useMemo(() => {
    const base = import.meta?.env?.VITE_API_BASE || DEFAULT_API_BASE
    return `${String(base).replace(/\/$/, '')}/api/control`
  }, [])
}

export function createControlClient(API_BASE) {
  return {
    async status({ timeoutMs = 4000 } = {}) {
      return await callApiWithRetry(`${API_BASE}/status`, { method: 'GET' }, { retries: 1, timeoutMs })
    },
    async action(endpoint, { method = 'POST', body, timeoutMs = 6000 } = {}) {
      return await callApiWithRetry(
        `${API_BASE}${endpoint}`,
        {
          method,
          body: body ? JSON.stringify(body) : undefined
        },
        { retries: 1, timeoutMs }
      )
    }
  }
}

/**
 * Polls /status and provides an `act` helper that refreshes status after actions.
 */
export function useControlStatus({ pollMs = 5000 } = {}) {
  const API_BASE = useControlApiBase()
  const client = useMemo(() => createControlClient(API_BASE), [API_BASE])

  const [status, setStatus] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState({})
  const [lastAction, setLastAction] = useState(null)

  const mountedRef = useRef(false)

  const fetchStatus = useCallback(async () => {
    try {
      const data = await client.status({ timeoutMs: 4000 })
      if (!mountedRef.current) return
      setStatus(data)
      setError(null)
    } catch (err) {
      if (!mountedRef.current) return
      setError(`無法取得系統狀態: ${err.message}`)
    }
  }, [client])

  useEffect(() => {
    mountedRef.current = true
    fetchStatus()
    const interval = setInterval(fetchStatus, pollMs)
    return () => {
      mountedRef.current = false
      clearInterval(interval)
    }
  }, [fetchStatus, pollMs])

  const act = useCallback(
    async (endpoint, { method = 'POST', body } = {}) => {
      const key = endpoint.split('/').pop()
      setLoading(prev => ({ ...prev, [key]: true }))
      setLastAction(null)
      try {
        const data = await client.action(endpoint, { method, body, timeoutMs: 6000 })
        setLastAction({ endpoint, message: data.message, warning: data.warning })
        await fetchStatus()
        return data
      } catch (err) {
        setError(`操作失敗: ${err.message}`)
        return null
      } finally {
        setLoading(prev => ({ ...prev, [key]: false }))
      }
    },
    [client, fetchStatus]
  )

  return { status, error, loading, lastAction, fetchStatus, act, API_BASE }
}
