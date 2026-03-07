// System monitoring API client + React hooks

import { useCallback, useEffect, useRef, useState } from 'react'
import { authFetch, getApiBase } from './auth'

async function fetchJson(url, { timeoutMs = 5000 } = {}) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const res = await authFetch(url, { signal: controller.signal })
    if (!res.ok) {
      let detail = ''
      try { const b = await res.json(); detail = b?.detail ? `: ${b.detail}` : '' } catch { }
      throw new Error(`API error: ${res.status}${detail}`)
    }
    return await res.json()
  } catch (err) {
    if (err?.name === 'AbortError') throw new Error('timeout')
    throw err
  } finally {
    clearTimeout(timer)
  }
}

async function postJson(url, payload, { timeoutMs = 8000 } = {}) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const res = await authFetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: controller.signal,
    })
    if (!res.ok) {
      let detail = ''
      try { const b = await res.json(); detail = b?.detail ? `: ${b.detail}` : '' } catch { }
      throw new Error(`API error: ${res.status}${detail}`)
    }
    return await res.json()
  } catch (err) {
    if (err?.name === 'AbortError') throw new Error('timeout')
    throw err
  } finally {
    clearTimeout(timer)
  }
}

function getBase() {
  return getApiBase()
}

function usePollingJson(path, { pollMs = 15000, timeoutMs = 5000 } = {}) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    try {
      const d = await fetchJson(`${getBase()}${path}`, { timeoutMs })
      setData(d)
      setError(null)
      return d
    } catch (e) {
      setError(e.message)
      throw e
    }
  }, [path, timeoutMs])

  useEffect(() => {
    let active = true
    async function run() {
      try {
        const d = await fetchJson(`${getBase()}${path}`, { timeoutMs })
        if (active) {
          setData(d)
          setError(null)
        }
      } catch (e) {
        if (active) setError(e.message)
      }
    }
    run()
    const t = setInterval(run, pollMs)
    return () => { active = false; clearInterval(t) }
  }, [path, pollMs, timeoutMs])

  return { data, error, refresh: load }
}

export function useSystemHealth({ pollMs = 5000 } = {}) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const timerRef = useRef(null)

  const fetch_ = useCallback(async () => {
    try {
      const d = await fetchJson(`${getBase()}/api/system/health`)
      setData(d)
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => {
    fetch_()
    timerRef.current = setInterval(fetch_, pollMs)
    return () => clearInterval(timerRef.current)
  }, [fetch_, pollMs])

  return { data, error, refresh: fetch_ }
}

export function useSystemQuota({ pollMs = 30000 } = {}) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let active = true
    async function load() {
      try {
        const d = await fetchJson(`${getBase()}/api/system/quota`)
        if (active) { setData(d); setError(null) }
      } catch (e) {
        if (active) setError(e.message)
      }
    }
    load()
    const t = setInterval(load, pollMs)
    return () => { active = false; clearInterval(t) }
  }, [pollMs])

  return { data, error }
}

export function useSystemRisk({ pollMs = 30000 } = {}) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let active = true
    async function load() {
      try {
        const d = await fetchJson(`${getBase()}/api/system/risk`)
        if (active) { setData(d); setError(null) }
      } catch (e) {
        if (active) setError(e.message)
      }
    }
    load()
    const t = setInterval(load, pollMs)
    return () => { active = false; clearInterval(t) }
  }, [pollMs])

  return { data, error }
}

export function useSystemEvents({ pollMs = 15000 } = {}) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let active = true
    async function load() {
      try {
        const d = await fetchJson(`${getBase()}/api/system/events`)
        if (active) { setData(d); setError(null) }
      } catch (e) {
        if (active) setError(e.message)
      }
    }
    load()
    const t = setInterval(load, pollMs)
    return () => { active = false; clearInterval(t) }
  }, [pollMs])

  return { data, error }
}

export function useQuarantineStatus({ pollMs = 15000 } = {}) {
  return usePollingJson('/api/system/quarantine-status', { pollMs })
}

export function useQuarantinePlan({ pollMs = 15000 } = {}) {
  return usePollingJson('/api/system/quarantine-plan', { pollMs })
}

export function useOpenIncidentClusters({ pollMs = 15000 } = {}) {
  const { data, error, refresh } = usePollingJson('/api/system/incidents/open', { pollMs })
  const [resolvingFingerprint, setResolvingFingerprint] = useState('')
  const [lastResolution, setLastResolution] = useState(null)

  const resolveCluster = useCallback(async ({ source, code, fingerprint, reason }) => {
    setResolvingFingerprint(fingerprint || `${source}|${code}`)
    try {
      const result = await postJson(`${getBase()}/api/system/incidents/resolve`, {
        source,
        code,
        fingerprint,
        reason,
      })
      setLastResolution(result)
      return result
    } finally {
      setResolvingFingerprint('')
    }
  }, [])

  return { data, error, refresh, resolveCluster, resolvingFingerprint, lastResolution }
}

export function useRemediationHistory({ pollMs = 15000, limit = 10 } = {}) {
  return usePollingJson(`/api/system/remediation-history?limit=${limit}`, { pollMs })
}

export function useQuarantineActions() {
  const [loading, setLoading] = useState({ apply: false, clear: false })
  const [lastAction, setLastAction] = useState(null)
  const [error, setError] = useState(null)

  const applySuggestedQuarantine = useCallback(async () => {
    setLoading(prev => ({ ...prev, apply: true }))
    try {
      const result = await postJson(`${getBase()}/api/system/quarantine/apply`, {})
      setLastAction({ type: 'apply', result })
      setError(null)
      return result
    } catch (e) {
      setError(e.message)
      return null
    } finally {
      setLoading(prev => ({ ...prev, apply: false }))
    }
  }, [])

  const clearAllQuarantine = useCallback(async () => {
    setLoading(prev => ({ ...prev, clear: true }))
    try {
      const result = await postJson(`${getBase()}/api/system/quarantine/clear`, { symbols: [] })
      setLastAction({ type: 'clear', result })
      setError(null)
      return result
    } catch (e) {
      setError(e.message)
      return null
    } finally {
      setLoading(prev => ({ ...prev, clear: false }))
    }
  }, [])

  return { loading, lastAction, error, applySuggestedQuarantine, clearAllQuarantine }
}

export function useCapital() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  const load = useCallback(async () => {
    try {
      const d = await fetchJson(`${getBase()}/api/capital`)
      setData(d)
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const save = useCallback(async (payload) => {
    setSaving(true)
    setSaved(false)
    try {
      const res = await authFetch(`${getBase()}/api/capital`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      if (!res.ok) throw new Error(`API ${res.status}`)
      const updated = await res.json()
      setData(updated)
      setError(null)
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }, [])

  return { data, error, saving, saved, save, refresh: load }
}
