/**
 * Auth utility — manage Bearer token and login state.
 *
 * Design doc §5.2: "FastAPI 後端加入基本認證（Bearer Token），
 * 即便 Tailscale 網路被突破，仍有第二層保護。"
 *
 * Redirect strategy:
 *   - Use window.location.replace() everywhere for maximum reliability.
 *   - React Router <Navigate> is NOT used for auth redirects because
 *     it can fail when the React tree is in an unstable state (e.g. polling
 *     hooks firing 401s while mount/unmount is in progress).
 */

const TOKEN_KEY = 'ai_trader_auth_token'

/** Get saved token from localStorage */
export function getToken() {
    try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
}

/** Save token to localStorage */
export function setToken(token) {
    try { localStorage.setItem(TOKEN_KEY, token) } catch { }
}

/** Remove ALL auth state */
export function clearToken() {
    try {
        localStorage.removeItem(TOKEN_KEY)
            // Also clear any other leftover keys from old sessions
            ;['auth_token', 'token', 'jwt'].forEach(k => localStorage.removeItem(k))
    } catch { }
}

/** Check if user is authenticated (has a non-empty saved token) */
export function isAuthenticated() {
    const t = getToken()
    return typeof t === 'string' && t.length > 0
}

/**
 * Resolve the API base URL.
 * Uses Vite's BASE_URL for subpath deployments (e.g. /ai-trader).
 * When VITE_API_BASE is set, use that directly as override.
 */
export function getApiBase() {
    if (import.meta?.env?.VITE_API_BASE) {
        return import.meta.env.VITE_API_BASE.replace(/\/$/, '')
    }
    return (import.meta.env.BASE_URL || '/').replace(/\/$/, '')
}

/** Redirect to login page — always reliable */
function redirectToLogin() {
    if (typeof window === 'undefined') return
    const base = (import.meta.env.BASE_URL || '/').replace(/\/$/, '')
    if (window.location.pathname.startsWith(`${base}/login`)) return   // already there
    window.location.replace(`${base}/login`)
}

/**
 * Enhanced fetch wrapper that automatically attaches the Bearer token.
 * On 401: clears token and redirects to /login via window.location.replace.
 */
export async function authFetch(url, options = {}) {
    const token = getToken()
    const headers = { ...options.headers }

    if (token) {
        headers['Authorization'] = `Bearer ${token}`
    }

    const res = await fetch(url, { ...options, headers })

    if (res.status === 401) {
        clearToken()
        // Notify any React listeners (optional, informational)
        try { window.dispatchEvent(new CustomEvent('auth:unauthorized')) } catch { }
        redirectToLogin()
        // Throw so callers know the request failed
        throw new Error('未授權，請重新登入')
    }

    return res
}

/**
 * Login — POSTs credentials and saves the returned token.
 * @returns {{ token: string, message: string }}
 */
export async function login(username, password) {
    const base = getApiBase()
    const res = await fetch(`${base}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
    })

    if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `登入失敗 (${res.status})`)
    }

    const data = await res.json()
    setToken(data.token)
    return data
}

/**
 * Logout — clear token and hard-redirect to /login.
 * Uses window.location.replace for guaranteed navigation regardless of
 * React Router or component state.
 */
export function logout() {
    clearToken()
    redirectToLogin()
}
