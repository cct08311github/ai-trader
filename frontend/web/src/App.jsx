import React, { Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { isAuthenticated } from './lib/auth'
import DashboardLayout from './layouts/DashboardLayout'
import LoginPage from './pages/Login'

// Lazy-loaded pages for code-splitting (reduces initial bundle size)
const PortfolioPage = React.lazy(() => import('./pages/Portfolio'))
const TradesPage = React.lazy(() => import('./pages/Trades'))
const StrategyPage = React.lazy(() => import('./pages/Strategy'))
const SystemPage = React.lazy(() => import('./pages/System'))
const AgentsPage = React.lazy(() => import('./pages/Agents'))
const AnalysisPage = React.lazy(() => import('./pages/Analysis'))
const SettingsPage = React.lazy(() => import('./pages/Settings'))

function PageFallback() {
  return (
    <div className="flex items-center justify-center min-h-[200px]">
      <div className="text-sm text-slate-400">讀取中…</div>
    </div>
  )
}

/**
 * Route guard — redirects to /login if not authenticated.
 * NOTE: The actual 401 redirect is handled by window.location.replace in auth.js.
 * This guard handles the case where a user navigates directly to a protected
 * route without a token in a fresh browser session.
 */
function RequireAuth({ children }) {
  if (!isAuthenticated()) {
    return <Navigate to="/login" replace />
  }
  return children
}

export default function App() {
  return (
    <Routes>
      {/* Public route */}
      <Route path="/login" element={<LoginPage />} />

      {/* Protected routes */}
      <Route
        element={
          <RequireAuth>
            <DashboardLayout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Navigate to="/portfolio" replace />} />
        <Route path="/portfolio" element={<Suspense fallback={<PageFallback />}><PortfolioPage /></Suspense>} />
        <Route path="/trades" element={<Suspense fallback={<PageFallback />}><TradesPage /></Suspense>} />
        <Route path="/strategy" element={<Suspense fallback={<PageFallback />}><StrategyPage /></Suspense>} />
        <Route path="/agents" element={<Suspense fallback={<PageFallback />}><AgentsPage /></Suspense>} />
        <Route path="/analysis" element={<Suspense fallback={<PageFallback />}><AnalysisPage /></Suspense>} />
        <Route path="/system" element={<Suspense fallback={<PageFallback />}><SystemPage /></Suspense>} />
        <Route path="/settings" element={<Suspense fallback={<PageFallback />}><SettingsPage /></Suspense>} />
      </Route>

      {/* Catch-all → login if no token, else portfolio */}
      <Route
        path="*"
        element={isAuthenticated() ? <Navigate to="/portfolio" replace /> : <Navigate to="/login" replace />}
      />
    </Routes>
  )
}
