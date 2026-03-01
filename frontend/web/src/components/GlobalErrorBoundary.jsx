/**
 * GlobalErrorBoundary — 全局錯誤邊界 (P2)
 * 捕捉 React 渲染錯誤，防止整個 App 白屏。
 * 設計書最佳實踐：任何頁面 crash 只影響當前區塊。
 */
import React from 'react'
import { AlertTriangle, RefreshCw, Home } from 'lucide-react'

export default class GlobalErrorBoundary extends React.Component {
    constructor(props) {
        super(props)
        this.state = { hasError: false, error: null, errorInfo: null }
    }

    static getDerivedStateFromError(error) {
        return { hasError: true, error }
    }

    componentDidCatch(error, errorInfo) {
        this.setState({ errorInfo })
        // Log to console for debugging
        console.error('[ErrorBoundary] Caught error:', error, errorInfo)
    }

    handleReload() {
        window.location.reload()
    }

    handleReset() {
        this.setState({ hasError: false, error: null, errorInfo: null })
    }

    render() {
        if (!this.state.hasError) return this.props.children

        const message = this.state.error?.message || '未知錯誤'
        const isDev = import.meta?.env?.DEV

        return (
            <div className="min-h-screen bg-slate-950 flex items-center justify-center p-6">
                <div className="w-full max-w-lg rounded-2xl border border-rose-500/30 bg-rose-500/5 p-8 shadow-2xl">
                    {/* Icon */}
                    <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-rose-500/10 ring-1 ring-rose-500/30">
                        <AlertTriangle className="h-7 w-7 text-rose-400" />
                    </div>

                    {/* Title */}
                    <h1 className="text-center text-xl font-bold text-slate-100 mb-2">
                        頁面發生錯誤
                    </h1>
                    <p className="text-center text-sm text-slate-400 mb-6">
                        系統捕捉到了一個渲染錯誤。您的交易資料並未受影響。
                    </p>

                    {/* Error detail (dev only) */}
                    {isDev && (
                        <div className="mb-5 rounded-xl border border-slate-800 bg-slate-900/60 p-4 font-mono text-xs text-rose-300 max-h-40 overflow-auto">
                            <div className="font-semibold mb-1">{message}</div>
                            {this.state.errorInfo?.componentStack && (
                                <pre className="text-slate-500 text-[10px] whitespace-pre-wrap">
                                    {this.state.errorInfo.componentStack.slice(0, 600)}
                                </pre>
                            )}
                        </div>
                    )}

                    {/* Actions */}
                    <div className="flex gap-3">
                        <button
                            onClick={this.handleReset.bind(this)}
                            className="flex-1 flex items-center justify-center gap-2 rounded-xl border border-slate-700
                         bg-slate-800/60 py-2.5 text-sm text-slate-300 transition hover:bg-slate-700/60"
                        >
                            <Home className="h-4 w-4" />
                            重試
                        </button>
                        <button
                            onClick={this.handleReload}
                            className="flex-1 flex items-center justify-center gap-2 rounded-xl
                         bg-gradient-to-r from-emerald-600 to-emerald-500 py-2.5 text-sm font-semibold
                         text-white shadow-lg transition hover:brightness-110"
                        >
                            <RefreshCw className="h-4 w-4" />
                            重新載入頁面
                        </button>
                    </div>
                </div>
            </div>
        )
    }
}
