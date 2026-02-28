import React from 'react'
import { Outlet } from 'react-router-dom'
import Sidebar from '../components/Sidebar'

export default function DashboardLayout() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto flex min-h-screen max-w-[1400px]">
        <Sidebar />
        <main className="flex-1 p-6">
          <div className="mb-6 flex items-center justify-between">
            <div>
              <div className="text-xs uppercase tracking-widest text-slate-400">Command Center</div>
              <h1 className="text-2xl font-semibold text-slate-100">AI Trader Dashboard</h1>
            </div>
            <div className="flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/40 px-3 py-2 text-xs text-slate-300 shadow-panel">
              <span className="inline-block h-2 w-2 rounded-full bg-emerald-400" />
              UI Online · API Pending
            </div>
          </div>

          <Outlet />

          <footer className="mt-10 border-t border-slate-900 pt-6 text-xs text-slate-500">
            Sprint 1 · Mock data enabled · API: <code className="text-slate-300">http://localhost:8080/api/portfolio/positions</code>
          </footer>
        </main>
      </div>
    </div>
  )
}
