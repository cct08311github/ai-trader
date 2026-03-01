/**
 * FloatingLogout — 全局懸浮登出按鈕 (右下角)
 *
 * 這個組件使用純 JavaScript 直接操作 localStorage 和 window.location，
 * 完全不依賴 React Router 或任何 context，確保在任何狀態下都能正常工作。
 *
 * 只在用戶已登入時顯示（localStorage 有 token）。
 */
import React, { useEffect, useState } from 'react'
import { LogOut, Key } from 'lucide-react'

const TOKEN_KEY = 'ai_trader_auth_token'

export default function FloatingLogout() {
    const [hasToken, setHasToken] = useState(false)
    const [tokenHint, setTokenHint] = useState('')
    const [expanded, setExpanded] = useState(false)

    useEffect(() => {
        function check() {
            try {
                const t = localStorage.getItem(TOKEN_KEY)
                setHasToken(typeof t === 'string' && t.length > 0)
                setTokenHint(t ? `…${t.slice(-6)}` : '')
            } catch {
                setHasToken(false)
            }
        }

        check()
        // Re-check on storage changes (cross-tab)
        window.addEventListener('storage', check)
        window.addEventListener('auth:unauthorized', check)
        return () => {
            window.removeEventListener('storage', check)
            window.removeEventListener('auth:unauthorized', check)
        }
    }, [])

    function handleForceLogout() {
        try { localStorage.clear() } catch { }
        window.location.replace('/login')
    }

    // Always render — even without token, show a minimal "Login" hint
    return (
        <div
            style={{
                position: 'fixed',
                bottom: '24px',
                right: '24px',
                zIndex: 99999,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'flex-end',
                gap: '8px',
            }}
        >
            {/* Expanded state — if mouse hovers, show details */}
            {expanded && (
                <div
                    style={{
                        backgroundColor: '#0f172a',
                        border: '1px solid #334155',
                        borderRadius: '12px',
                        padding: '12px 16px',
                        fontSize: '12px',
                        color: '#94a3b8',
                        maxWidth: '220px',
                        boxShadow: '0 20px 40px rgba(0,0,0,0.5)',
                    }}
                >
                    <div style={{ color: '#f8fafc', fontWeight: 600, marginBottom: 6 }}>登入狀態</div>
                    {hasToken ? (
                        <>
                            <div style={{ color: '#10b981', marginBottom: 4 }}>✓ 已登入</div>
                            <div style={{ fontFamily: 'monospace', color: '#64748b', marginBottom: 10 }}>
                                Token {tokenHint}
                            </div>
                        </>
                    ) : (
                        <div style={{ color: '#f43f5e', marginBottom: 10 }}>✗ 未登入</div>
                    )}
                    <button
                        onClick={handleForceLogout}
                        style={{
                            width: '100%',
                            padding: '8px 12px',
                            backgroundColor: '#be123c',
                            color: 'white',
                            border: 'none',
                            borderRadius: '8px',
                            fontSize: '12px',
                            fontWeight: 600,
                            cursor: 'pointer',
                        }}
                    >
                        🔑 清除登入 → 跳转登入頁
                    </button>
                </div>
            )}

            {/* Floating button — always visible */}
            <button
                onClick={() => setExpanded(v => !v)}
                title="登入/登出管理"
                style={{
                    width: '48px',
                    height: '48px',
                    borderRadius: '50%',
                    backgroundColor: hasToken ? '#065f46' : '#7f1d1d',
                    border: `2px solid ${hasToken ? '#10b981' : '#f43f5e'}`,
                    color: hasToken ? '#10b981' : '#f43f5e',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    cursor: 'pointer',
                    boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
                    transition: 'transform 0.2s',
                }}
                onMouseEnter={e => e.currentTarget.style.transform = 'scale(1.1)'}
                onMouseLeave={e => e.currentTarget.style.transform = 'scale(1)'}
            >
                {hasToken ? <LogOut size={20} /> : <Key size={20} />}
            </button>
        </div>
    )
}
