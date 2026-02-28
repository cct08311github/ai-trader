import React, { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { Menu, X } from 'lucide-react'
import Sidebar from '../components/Sidebar'
import GlobalControlBar from '../components/GlobalControlBar'
import Breadcrumbs from '../components/Breadcrumbs'
import ThemeToggle from '../components/ThemeToggle'

export default function DashboardLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)

  return (
    <div className="min-h-screen bg-[rgb(var(--bg))] text-[rgb(var(--text))]">
      <div className="mx-auto flex min-h-screen w-full max-w-[1400px]">
        {/* Desktop sidebar */}
        <div className="hidden lg:block">
          <Sidebar />
        </div>

        {/* Mobile off-canvas sidebar */}
        {sidebarOpen ? (
          <div className="lg:hidden">
            <div
              className="fixed inset-0 z-40 bg-black/60"
              aria-hidden="true"
              onClick={() => setSidebarOpen(false)}
            />
            <div className="fixed inset-y-0 left-0 z-50 w-72 max-w-[90vw]">
              <Sidebar onNavigate={() => setSidebarOpen(false)} />
            </div>
          </div>
        ) : null}

        <main className="flex-1 p-4 sm:p-6">
          <div className="mb-6 flex flex-col gap-3">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex items-start gap-3">
                <button
                  type="button"
                  className="lg:hidden mt-1 inline-flex items-center justify-center rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.35] p-2 hover:bg-[rgb(var(--surface))/0.5]"
                  aria-label={sidebarOpen ? '關閉側邊欄' : '開啟側邊欄'}
                  onClick={() => setSidebarOpen((v) => !v)}
                >
                  {sidebarOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
                </button>

                <div>
                  <div className="text-xs uppercase tracking-widest text-[rgb(var(--muted))]">Command Center</div>
                  <h1 className="text-2xl font-semibold">AI Trader Dashboard</h1>
                  <div className="mt-2">
                    <Breadcrumbs />
                  </div>
                </div>
              </div>

              <div className="flex flex-col gap-2 lg:items-end">
                <div className="flex items-center justify-between gap-2 lg:justify-end">
                  <ThemeToggle />
                </div>

                {/* Global control bar: visible on all pages */}
                <div className="lg:flex-1 lg:flex lg:justify-end">
                  <GlobalControlBar />
                </div>
              </div>
            </div>
          </div>

          <Outlet />

          <footer className="mt-10 border-t border-[rgb(var(--border))] pt-6 text-xs text-[rgb(var(--muted))]">
            Sprint 1 · Mock data enabled · API:{' '}
            <code className="text-[rgb(var(--text))]">http://localhost:8080/api/portfolio/positions</code>
          </footer>
        </main>
      </div>
    </div>
  )
}
