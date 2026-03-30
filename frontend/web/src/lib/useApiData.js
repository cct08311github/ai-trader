/**
 * useApiData — 封裝 fetch + loading + error + abort + retry 的 React hook。
 *
 * 用法：
 *   const { data, error, loading, refetch } = useApiData('/api/portfolio/positions')
 *
 *   // or with options
 *   const { data } = useApiData('/api/positions', {
 *     method: 'POST',
 *     body: { symbol: '2330' },
 *     retry: 2,
 *     deps: [symbol],   // re-fetch when symbol changes
 *   })
 *
 * 狀態：
 *   loading=true  → 首次載入中
 *   error != null → 請求失敗（可重試）
 *   data != null  → 成功取得資料
 *   data=null + error=null → 尚未請求（skip=true 時）
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiFetch } from './apiFetch'

export function useApiData(url, options = {}) {
  const {
    method = 'GET',
    body,
    retry = 1,
    timeout,
    skip = false,
    deps = [],
  } = options

  const [state, setState] = useState({
    data: null,
    error: null,
    loading: !skip,
  })

  const controllerRef = useRef(null)
  const mountedRef = useRef(true)

  const fetch_ = useCallback(async () => {
    // Abort previous
    if (controllerRef.current) {
      controllerRef.current.abort()
    }
    controllerRef.current = new AbortController()

    if (!mountedRef.current) return

    setState(prev => ({ ...prev, loading: true, error: null }))

    const result = await apiFetch(url, {
      method,
      body,
      retry,
      timeout,
      signal: controllerRef.current.signal,
    })

    if (!mountedRef.current) return

    setState({
      data: result.data,
      error: result.error,
      loading: false,
    })
  }, [url, method, body, retry, timeout]) // eslint-disable-line

  useEffect(() => {
    mountedRef.current = true
    if (skip) {
      setState({ data: null, error: null, loading: false })
      return
    }
    fetch_()

    return () => {
      mountedRef.current = false
      if (controllerRef.current) {
        controllerRef.current.abort()
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetch_, skip, ...deps])

  const refetch = useCallback(() => {
    if (!skip) fetch_()
  }, [fetch_, skip])

  return { ...state, refetch }
}
