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

function getBase() {
  return getApiBase()
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
