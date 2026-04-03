import React, { Suspense, useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { isAuthenticated } from './lib/auth'
import DashboardLayout from './layouts/DashboardLayout'
import LoginPage from './pages/Login'

// ── Battle theme + variant switcher (loaded once at app root) ───────────────
import BattleTheme, { useBattleTheme } from './components/BattleTheme'
import VariantSwitcher from './components/VariantSwitcher'

// Lazy-loaded pages (code-splitting)
const PortfolioPage = React.lazy(() => import('./pages/PortfolioPage'))
const TradesPage     = React.lazy(() => import('./pages/Trades'))
const StrategyPage   = React.lazy(() => import('./pages/Strategy'))
const SystemPage     = React.lazy(() => import('./pages/System'))
const AgentsPage     = React.lazy(() => import('./pages/Agents'))
const AnalysisPage   = React.lazy(() => import('./pages/Analysis'))
const SettingsPage   = React.lazy(() => import('./pages/Settings'))

// Restore variant preference from sessionStorage
const STORAGE_KEY = 'ai-trader-theme-variant'
const savedVariant = sessionStorage.getItem(STORAGE_KEY) as 'A' | 'B' | 'C' | null
const initialVariant = savedVariant ?? 'A'

function PageFallback() {
  return (
    <div className="flex items-center justify-center min-h-[200px]">
      <div className="text-sm text-slate-400">讀取中…</div>
    </div>
  )
}

/** Route guard — redirects to /login if not authenticated. */
function RequireAuth({ children }) {
  if (!isAuthenticated()) {
    return <Navigate to="/login" replace />
  }
  return children
}

/** Inner layout that patches VariantSwitcher into the existing DashboardLayout */
function BattleLayout() {
  // Apply variant tokens to <html> on mount
  useBattleTheme(initialVariant)
  return <DashboardLayout variantSwitcher={<VariantSwitcher />} />
}

export default function App() {
  return (
    <>
      {/* Inject Google Fonts + global keyframes once */}
      <BattleTheme />

      <Routes>
        {/* Public route */}
        <Route path="/login" element={<LoginPage />} />

        {/* Protected routes — all wrapped in BattleLayout */}
        <Route
          element={
            <RequireAuth>
              <BattleLayout />
            </RequireAuth>
          }
        >
          <Route path="/" element={<Navigate to="/portfolio" replace />} />
          <Route
            path="/portfolio"
            element={
              <Suspense fallback={<PageFallback />}>
                <PortfolioPage />
              </Suspense>
            }
          />
          <Route
            path="/trades"
            element={
              <Suspense fallback={<PageFallback />}>
                <TradesPage />
              </Suspense>
            }
          />
          <Route
            path="/strategy"
            element={
              <Suspense fallback={<PageFallback />}>
                <StrategyPage />
              </Suspense>
            }
          />
          <Route
            path="/agents"
            element={
              <Suspense fallback={<PageFallback />}>
                <AgentsPage />
              </Suspense>
            }
          />
          <Route
            path="/analysis"
            element={
              <Suspense fallback={<PageFallback />}>
                <AnalysisPage />
              </Suspense>
            }
          />
          <Route
            path="/system"
            element={
              <Suspense fallback={<PageFallback />}>
                <SystemPage />
              </Suspense>
            }
          />
          <Route
            path="/settings"
            element={
              <Suspense fallback={<PageFallback />}>
                <SettingsPage />
              </Suspense>
            }
          />
        </Route>

        {/* Catch-all */}
        <Route
          path="*"
          element={isAuthenticated() ? <Navigate to="/portfolio" replace /> : <Navigate to="/login" replace />}
        />
      </Routes>
    </>
  )
}
