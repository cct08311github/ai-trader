import React from 'react'

/** Section wrapper */
export default function DetailSection({ icon: Icon, title, children }) {
    return (
        <div className="rounded-xl border border-slate-800/80 bg-slate-900/40 p-4">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-200">
                <Icon className="h-4 w-4 text-emerald-400" />
                {title}
            </div>
            {children}
        </div>
    )
}
