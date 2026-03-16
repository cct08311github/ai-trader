import React from 'react'
import { Lock, Unlock } from 'lucide-react'

/**
 * Lock/unlock button rendered inside the drawer header.
 * Props:
 *   isLocked     — boolean
 *   lockLoading  — boolean
 *   onToggle     — () => void
 */
export default function PositionLocks({ isLocked, lockLoading, onToggle }) {
    return (
        <button
            onClick={onToggle}
            disabled={lockLoading}
            title={isLocked ? '解除鎖定（允許賣出）' : '鎖定（禁止 AI 賣出）'}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-50 ${isLocked
                    ? 'bg-amber-500/15 text-amber-400 hover:bg-amber-500/25 ring-1 ring-amber-500/30'
                    : 'bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-slate-200'
                }`}
        >
            {isLocked ? <Unlock className="h-3.5 w-3.5" /> : <Lock className="h-3.5 w-3.5" />}
            {lockLoading ? '處理中…' : isLocked ? '解除鎖定' : '鎖定持股'}
        </button>
    )
}
