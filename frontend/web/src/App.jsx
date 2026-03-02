import React from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { isAuthenticated } from './lib/auth'
import DashboardLayout from './layouts/DashboardLayout'
import LoginPage from './pages/Login'
import PortfolioPage from './pages/Portfolio'
import TradesPage from './pages/Trades'
import StrategyPage from './pages/Strategy'
import SystemPage from './pages/System'
import AgentsPage from './pages/Agents'
import SettingsPage from './pages/Settings'

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
        <Route path="/portfolio" element={<PortfolioPage />} />
        <Route path="/trades" element={<TradesPage />} />
        <Route path="/strategy" element={<StrategyPage />} />
        <Route path="/agents" element={<AgentsPage />} />
        <Route path="/system" element={<SystemPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>

      {/* Catch-all → login if no token, else portfolio */}
      <Route
        path="*"
        element={isAuthenticated() ? <Navigate to="/portfolio" replace /> : <Navigate to="/login" replace />}
      />
    </Routes>
  )
}
