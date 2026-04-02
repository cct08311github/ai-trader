/**
 * apiFetch.js — 統一 API fetch wrapper。
 *
 * 功能：
 * - 自動帶 Bearer token
 * - 統一錯誤處理（401 → auth event, 5xx → retry with backoff）
 * - 可選 retry（預設 1 次，間隔 2s）
 *
 * 用法：
 *   import { apiFetch } from './apiFetch'
 *
 *   // Basic
 *   const data = await apiFetch('/api/portfolio/positions')
 *
 *   // With options
 *   const data = await apiFetch('/api/positions', {
 *     method: 'POST',
 *     body: JSON.stringify({ symbol: '2330' }),
 *     retry: 2,
 *     timeout: 15000,
 *   })
 *
 *   // Returns { data, error, status }
 */

import { getToken } from './auth'

const DEFAULT_TIMEOUT = 10000 // 10s

/**
 * @param {string} url — relative or absolute URL
 * @param {object} options
 * @param {number} [options.retry=1] — number of retries on 5xx
 * @param {number} [options.timeout=10000]
 * @param {'get'|'post'|'put'|'delete'|'patch'} [options.method]
 * @param {any} [options.body]
 * @param {AbortSignal} [options.signal]
 */
export async function apiFetch(url, options = {}) {
  const {
    retry = 1,
    timeout = DEFAULT_TIMEOUT,
    method = 'GET',
    body,
    signal: externalSignal,
    ...rest
  } = options

  // Prepend Vite base path for subpath deployments (e.g. /ai-trader/api/...)
  const base = (import.meta.env.BASE_URL || '/').replace(/\/$/, '')
  const resolvedUrl = url.startsWith('/') && !url.startsWith(base) ? `${base}${url}` : url

  const token = getToken()
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(rest.headers || {}),
  }

  let controller
  let timeoutId
  let signal = externalSignal

  if (!externalSignal) {
    controller = new AbortController()
    signal = controller.signal
    timeoutId = setTimeout(() => controller.abort(), timeout)
  }

  async function attempt(remainingRetries) {
    try {
      const res = await fetch(resolvedUrl, {
        method,
        headers,
        body: body != null ? JSON.stringify(body) : undefined,
        signal,
        ...rest,
      })

      // 401 → fire auth event and return error
      if (res.status === 401) {
        window.dispatchEvent(new Event('auth:unauthorized'))
        const text = await res.text().catch(() => '')
        return { data: null, error: `未授權（401）${text}`, status: 401 }
      }

      // 5xx → retry
      if (res.status >= 500 && remainingRetries > 0) {
        await sleep(2000)
        return attempt(remainingRetries - 1)
      }

      // 4xx (non-401) → parse error
      if (res.status >= 400 && res.status < 500) {
        const text = await res.text().catch(() => '')
        return { data: null, error: `客戶端錯誤（${res.status}）${text}`, status: res.status }
      }

      // Success
      const contentType = res.headers.get('content-type') || ''
      const data = contentType.includes('application/json')
        ? await res.json().catch(() => null)
        : await res.text().catch(() => null)

      return { data, error: null, status: res.status }
    } catch (err) {
      if (err.name === 'AbortError') {
        return { data: null, error: `請求超時（${timeout}ms）`, status: 0 }
      }
      if (remainingRetries > 0) {
        await sleep(2000)
        return attempt(remainingRetries - 1)
      }
      return { data: null, error: `網路錯誤：${err.message}`, status: 0 }
    }
  }

  try {
    return await attempt(retry)
  } finally {
    if (timeoutId) clearTimeout(timeoutId)
    if (controller) controller.abort()
  }
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}
