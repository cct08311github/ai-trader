/**
 * Toast notification system — P2 通知中心
 * 使用 React context + custom event 提供全局 toast 通知。
 *
 * 用法：
 *   import { useToast } from './ToastProvider'
 *   const toast = useToast()
 *   toast.success('持倉已更新')
 *   toast.error('API 請求失敗')
 *   toast.warn('板塊集中度超過 40%')
 *   toast.info('系統狀態：正常')
 */
import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { CheckCircle, AlertTriangle, XCircle, Info, X } from 'lucide-react'

const ToastContext = createContext(null)

const CONFIGS = {
    success: { icon: CheckCircle, border: 'border-emerald-500/40', bg: 'bg-emerald-500/10', iconColor: 'text-emerald-400', titleColor: 'text-emerald-300' },
    error: { icon: XCircle, border: 'border-rose-500/40', bg: 'bg-rose-500/10', iconColor: 'text-rose-400', titleColor: 'text-rose-300' },
    warn: { icon: AlertTriangle, border: 'border-amber-500/40', bg: 'bg-amber-500/10', iconColor: 'text-amber-400', titleColor: 'text-amber-300' },
    info: { icon: Info, border: 'border-sky-500/40', bg: 'bg-sky-500/10', iconColor: 'text-sky-400', titleColor: 'text-sky-300' },
}

let _globalToast = null

function Toast({ id, type = 'info', message, onDismiss }) {
    const cfg = CONFIGS[type] || CONFIGS.info
    const Icon = cfg.icon
    const [visible, setVisible] = useState(false)

    useEffect(() => {
        // Animate in
        const t = setTimeout(() => setVisible(true), 10)
        return () => clearTimeout(t)
    }, [])

    function dismiss() {
        setVisible(false)
        setTimeout(() => onDismiss(id), 300)
    }

    return (
        <div
            className={`flex items-start gap-3 rounded-xl border ${cfg.border} ${cfg.bg}
                  px-4 py-3 shadow-2xl backdrop-blur-xl
                  transition-all duration-300 ease-out
                  ${visible ? 'opacity-100 translate-x-0' : 'opacity-0 translate-x-12'}`}
        >
            <Icon className={`h-4 w-4 mt-0.5 shrink-0 ${cfg.iconColor}`} />
            <p className={`flex-1 text-sm font-medium ${cfg.titleColor}`}>{message}</p>
            <button
                onClick={dismiss}
                className="shrink-0 text-slate-500 hover:text-slate-300 transition-colors"
                aria-label="關閉通知"
            >
                <X className="h-3.5 w-3.5" />
            </button>
        </div>
    )
}

export function ToastProvider({ children }) {
    const [toasts, setToasts] = useState([])
    const idRef = useRef(0)

    const MAX_TOASTS = 8

    const push = useCallback((type, message, duration = 4000) => {
        const id = ++idRef.current
        setToasts(prev => {
            if (prev.length >= MAX_TOASTS) {
                // Show overflow notice, then add new toast
                const overflow = prev.length - MAX_TOASTS + 1
                const overflowToast = { id: -(overflow + 100), type: 'info', message: `還有 ${overflow} 則通知被折疊`, isOverflow: true }
                const trimmed = prev.slice(-(MAX_TOASTS - 1))
                return [...trimmed, { id, type, message }, overflowToast]
            }
            return [...prev, { id, type, message }]
        })
        if (duration > 0) {
            setTimeout(() => dismiss(id), duration)
        }
        return id
    }, [])

    function dismiss(id) {
        setToasts(prev => prev.filter(t => t.id !== id))
    }

    function dismissAll() {
        setToasts([])
    }

    const api = {
        success: (msg, dur) => push('success', msg, dur ?? 4000),
        error: (msg) => push('error', msg, 0), // Critical/error — no auto-dismiss
        warn: (msg, dur) => push('warn', msg, dur ?? 0), // warn — no auto-dismiss either
        info: (msg, dur) => push('info', msg, dur),
        dismiss,
        dismissAll,
    }

    // Expose globally so auth.js and other non-React code can call it
    useEffect(() => { _globalToast = api }, [api])

    // Listen for custom events (from authFetch 401, etc.)
    useEffect(() => {
        function onUnauthorized() {
            api.warn('登入已過期，請重新登入', 5000)
        }
        window.addEventListener('auth:unauthorized', onUnauthorized)
        return () => window.removeEventListener('auth:unauthorized', onUnauthorized)
    }, [])

    return (
        <ToastContext.Provider value={api}>
            {children}
            {/* Toast container — bottom-right */}
            <div
                aria-live="polite"
                className="fixed bottom-4 right-4 z-[9999] flex flex-col gap-2 w-80 max-w-[calc(100vw-2rem)]"
            >
                {toasts.map(t => (
                    <Toast key={t.id} {...t} onDismiss={dismiss} />
                ))}
            </div>
        </ToastContext.Provider>
    )
}

export function useToast() {
    const ctx = useContext(ToastContext)
    if (!ctx) throw new Error('useToast must be used inside <ToastProvider>')
    return ctx
}

/** Call toast from outside React (e.g. auth.js). Must be inside ToastProvider. */
export function globalToast(type, message, duration) {
    if (_globalToast) _globalToast[type]?.(message, duration)
}
