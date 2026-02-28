import React from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import DashboardLayout from './layouts/DashboardLayout'
import PortfolioPage from './pages/Portfolio'
import TradesPage from './pages/Trades'
import StrategyPage from './pages/Strategy'
import SystemPage from './pages/System'

export default function App() {
  return (
    <Routes>
      <Route element={<DashboardLayout />}>
        <Route path="/" element={<Navigate to="/portfolio" replace />} />
        <Route path="/portfolio" element={<PortfolioPage />} />
        <Route path="/trades" element={<TradesPage />} />
        <Route path="/strategy" element={<StrategyPage />} />
        <Route path="/system" element={<SystemPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/portfolio" replace />} />
    </Routes>
  )
}
