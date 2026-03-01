import React, { useEffect, useState } from 'react'
import { isAuthenticated, login } from '../lib/auth'
import { Lock, User, AlertTriangle, Eye, EyeOff, Shield } from 'lucide-react'

export default function LoginPage() {
    const [username, setUsername] = useState('')
    const [password, setPassword] = useState('')
    const [showPassword, setShowPassword] = useState(false)
    const [error, setError] = useState('')
    const [loading, setLoading] = useState(false)

    // If already logged in, redirect away
    useEffect(() => {
        if (isAuthenticated()) {
            window.location.replace('/portfolio')
        }
    }, [])

    const handleSubmit = async (e) => {
        e.preventDefault()
        setError('')
        setLoading(true)
        try {
            await login(username, password)
            // Hard redirect so the entire app re-initialises with the new token
            window.location.replace('/portfolio')
        } catch (err) {
            setError(err.message || '登入失敗')
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 p-4">
            {/* Ambient glow */}
            <div className="pointer-events-none fixed inset-0">
                <div className="absolute left-1/2 top-1/3 -translate-x-1/2 -translate-y-1/2 h-[600px] w-[600px] rounded-full bg-emerald-500/5 blur-[120px]" />
                <div className="absolute right-1/4 bottom-1/4 h-[400px] w-[400px] rounded-full bg-cyan-500/5 blur-[100px]" />
            </div>

            <div className="relative w-full max-w-md">
                {/* Logo / branding */}
                <div className="mb-8 text-center">
                    <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-500/20 to-cyan-500/20 ring-1 ring-emerald-500/30 backdrop-blur-sm">
                        <Shield className="h-8 w-8 text-emerald-400" />
                    </div>
                    <h1 className="text-2xl font-bold text-slate-100">AI Trader Command Center</h1>
                    <p className="mt-2 text-sm text-slate-400">前端戰情監控系統</p>
                </div>

                {/* Login card */}
                <form
                    onSubmit={handleSubmit}
                    className="rounded-2xl border border-slate-800/80 bg-slate-900/60 p-8 shadow-2xl backdrop-blur-xl"
                >
                    <h2 className="mb-6 text-lg font-semibold text-slate-200">登入系統</h2>

                    {error && (
                        <div className="mb-4 flex items-center gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
                            <AlertTriangle className="h-4 w-4 flex-shrink-0" />
                            <span>{error}</span>
                        </div>
                    )}

                    {/* Username */}
                    <div className="mb-4">
                        <label htmlFor="login-username" className="mb-1.5 block text-sm font-medium text-slate-300">
                            帳號
                        </label>
                        <div className="relative">
                            <User className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
                            <input
                                id="login-username"
                                type="text"
                                autoComplete="username"
                                required
                                value={username}
                                onChange={(e) => setUsername(e.target.value)}
                                placeholder="admin"
                                className="w-full rounded-xl border border-slate-700 bg-slate-800/60 py-2.5 pl-10 pr-4 text-sm text-slate-100 placeholder:text-slate-500 transition-colors focus:border-emerald-500/50 focus:outline-none focus:ring-2 focus:ring-emerald-500/20"
                            />
                        </div>
                    </div>

                    {/* Password */}
                    <div className="mb-6">
                        <label htmlFor="login-password" className="mb-1.5 block text-sm font-medium text-slate-300">
                            密碼
                        </label>
                        <div className="relative">
                            <Lock className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
                            <input
                                id="login-password"
                                type={showPassword ? 'text' : 'password'}
                                autoComplete="current-password"
                                required
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                placeholder="••••••••"
                                className="w-full rounded-xl border border-slate-700 bg-slate-800/60 py-2.5 pl-10 pr-12 text-sm text-slate-100 placeholder:text-slate-500 transition-colors focus:border-emerald-500/50 focus:outline-none focus:ring-2 focus:ring-emerald-500/20"
                            />
                            <button
                                type="button"
                                onClick={() => setShowPassword(!showPassword)}
                                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition-colors"
                                aria-label={showPassword ? '隱藏密碼' : '顯示密碼'}
                            >
                                {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                            </button>
                        </div>
                    </div>

                    {/* Submit */}
                    <button
                        type="submit"
                        disabled={loading}
                        className="w-full rounded-xl bg-gradient-to-r from-emerald-600 to-emerald-500 py-2.5 text-sm font-semibold text-white shadow-lg shadow-emerald-500/20 transition-all hover:shadow-emerald-500/30 hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        {loading ? (
                            <span className="flex items-center justify-center gap-2">
                                <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                                </svg>
                                驗證中…
                            </span>
                        ) : (
                            '登入'
                        )}
                    </button>

                    {/* Security note */}
                    <p className="mt-6 text-center text-xs text-slate-500">
                        🔒 連線受 Tailscale VPN + Bearer Token 雙重保護
                    </p>
                </form>
            </div>
        </div>
    )
}
