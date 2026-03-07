import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ThemeProvider } from '../lib/theme'
import { ToastProvider } from '../components/ToastProvider'
import StrategyPage from './Strategy'

// Mock EventSource (Strategy.jsx uses it for live trace stream)
class MockEventSource {
  constructor(url) { this.url = url; this.listeners = {} }
  addEventListener(event, cb) { this.listeners[event] = cb }
  close() { }
}
global.EventSource = MockEventSource

// Mock fetch (used by StrategyPage for proposals + traces)
global.fetch = vi.fn(() =>
  Promise.resolve({
    ok: true,
    json: () => Promise.resolve({ status: 'ok', data: [], total: 0 }),
  })
)

vi.mock('../lib/auth', () => ({
  authFetch: vi.fn(() =>
    Promise.resolve({
      ok: true,
      json: () => Promise.resolve({ status: 'ok', data: [], total: 0 }),
    })
  ),
  getToken: vi.fn(() => 'test-token'),
  getApiBase: vi.fn(() => 'http://localhost:8080'),
}))

function renderPage() {
  return render(
    <ThemeProvider defaultTheme="dark">
      <ToastProvider>
        <MemoryRouter initialEntries={['/strategy']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <StrategyPage />
        </MemoryRouter>
      </ToastProvider>
    </ThemeProvider>
  )
}

describe('StrategyPage', () => {

  it('renders without crashing', async () => {
    renderPage()
    expect(await screen.findByText(/策略提案/)).toBeInTheDocument()
  })

  it('shows 策略提案 section heading', async () => {
    renderPage()
    expect((await screen.findAllByText(/策略提案/)).length).toBeGreaterThan(0)
  })

  it('shows proposals table headers', async () => {
    renderPage()
    await screen.findByText(/策略提案/)
    // Table should have these headers (column header is '標的', not '股票')
    expect(screen.getByText('標的')).toBeInTheDocument()
    expect(screen.getByText('方向')).toBeInTheDocument()
    expect(screen.getByText('狀態')).toBeInTheDocument()
  })

  it('shows LLM traces section', async () => {
    renderPage()
    await screen.findByText(/策略提案/)
    expect((await screen.findAllByText(/決策日誌|LLM Traces|llm/i)).length).toBeGreaterThan(0)
  })

  it('table has overflow-auto wrapper for mobile scroll', () => {
    renderPage()
    // The outer container has overflow-auto (mobile fix)
    const overflowEl = document.querySelector('.overflow-auto')
    expect(overflowEl).not.toBeNull()
  })

  it('table uses min-w-full on mobile', () => {
    renderPage()
    // The table should NOT have min-w-[980px] without sm: prefix
    const table = document.querySelector('table')
    if (table) {
      // Should have min-w-full (or sm:min-w-[980px])
      expect(table.className).toMatch(/min-w-full/)
    }
  })
})
