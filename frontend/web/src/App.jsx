import React, { Suspense, useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { isAuthenticated } from './lib/auth'
import { queryClient } from './lib/queryClient'
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

// ── Research / new routes (lazy) ────────────────────────────────────────────
const ResearchLayout    = React.lazy(() => import('./layouts/ResearchLayout'))
const ResearchDashboard = React.lazy(() => import('./pages/research/ResearchDashboard'))
const StockResearch     = React.lazy(() => import('./pages/research/StockResearch'))
const Screener          = React.lazy(() => import('./pages/research/Screener'))
const DashboardPage     = React.lazy(() => import('./pages/Dashboard'))
const RiskPage          = React.lazy(() => import('./pages/Risk'))
const GeopoliticalPage  = React.lazy(() => import('./pages/Geopolitical'))
const ReportsPage       = React.lazy(() => import('./pages/Reports'))

// Restore variant preference from sessionStorage
const STORAGE_KEY = 'ai-trader-theme-variant'
const savedVariant = sessionStorage.getItem(STORAGE_KEY)
const initialVariant = ['A', 'B', 'C'].includes(savedVariant) ? savedVariant : 'A'

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
    <QueryClientProvider client={queryClient}>
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
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
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

          {/* Research nested routes */}
          <Route
            path="/research"
            element={
              <Suspense fallback={<PageFallback />}>
                <ResearchLayout />
              </Suspense>
            }
          >
            <Route
              index
              element={
                <Suspense fallback={<PageFallback />}>
                  <ResearchDashboard />
                </Suspense>
              }
            />
            <Route
              path="stock"
              element={
                <Suspense fallback={<PageFallback />}>
                  <StockResearch />
                </Suspense>
              }
            />
            <Route
              path="screener"
              element={
                <Suspense fallback={<PageFallback />}>
                  <Screener />
                </Suspense>
              }
            />
          </Route>

          {/* Top-level new routes */}
          <Route
            path="/dashboard"
            element={
              <Suspense fallback={<PageFallback />}>
                <DashboardPage />
              </Suspense>
            }
          />
          <Route
            path="/risk"
            element={
              <Suspense fallback={<PageFallback />}>
                <RiskPage />
              </Suspense>
            }
          />
          <Route
            path="/geopolitical"
            element={
              <Suspense fallback={<PageFallback />}>
                <GeopoliticalPage />
              </Suspense>
            }
          />
          <Route
            path="/reports"
            element={
              <Suspense fallback={<PageFallback />}>
                <ReportsPage />
              </Suspense>
            }
          />
        </Route>

        {/* Catch-all */}
        <Route
          path="*"
          element={isAuthenticated() ? <Navigate to="/dashboard" replace /> : <Navigate to="/login" replace />}
        />
      </Routes>
    </QueryClientProvider>
  )
}
