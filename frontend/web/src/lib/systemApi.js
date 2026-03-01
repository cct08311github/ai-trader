// System monitoring API client + React hooks

import { useCallback, useEffect, useRef, useState } from 'react'

const DEFAULT_API_BASE = 'http://localhost:8080'

async function fetchJson(url, { timeoutMs = 5000 } = {}) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const res = await fetch(url, { signal: controller.signal })
    if (!res.ok) throw new Error(`API ${res.status}`)
    return await res.json()
  } catch (err) {
    if (err?.name === 'AbortError') throw new Error('timeout')
    throw err
  } finally {
    clearTimeout(timer)
  }
}

function getBase() {
  return (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_BASE) || DEFAULT_API_BASE
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
