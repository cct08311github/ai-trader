import React from 'react'
import { Outlet } from 'react-router-dom'
import Sidebar from '../components/Sidebar'
import GlobalControlBar from '../components/GlobalControlBar'

export default function DashboardLayout() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto flex min-h-screen max-w-[1400px]">
        <Sidebar />
        <main className="flex-1 p-6">
          <div className="mb-6 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div className="text-xs uppercase tracking-widest text-slate-400">Command Center</div>
              <h1 className="text-2xl font-semibold text-slate-100">AI Trader Dashboard</h1>
            </div>

            {/* Global control bar: visible on all pages */}
            <div className="lg:flex-1 lg:flex lg:justify-end">
              <GlobalControlBar />
            </div>
          </div>

          <Outlet />

          <footer className="mt-10 border-t border-slate-900 pt-6 text-xs text-slate-500">
            Sprint 1 · Mock data enabled · API:{' '}
            <code className="text-slate-300">http://localhost:8080/api/portfolio/positions</code>
          </footer>
        </main>
      </div>
    </div>
  )
}
