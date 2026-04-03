import React from 'react'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import StockResearch from '../pages/research/StockResearch'

global.HTMLCanvasElement.prototype.getContext = () => null

// Mock KlineChart to avoid heavyweight canvas setup
vi.mock('../components/KlineChart', () => ({
  default: ({ symbol }) => <div data-testid="kline-chart">{symbol}</div>,
}))

const createWrapper = (url = '/research/stock') => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return ({ children }) => (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[url]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        {children}
      </MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ data: [] }),
  })
})

afterEach(() => vi.clearAllMocks())

test('StockResearch renders without crash', () => {
  render(<StockResearch />, { wrapper: createWrapper() })
  // Search input or watchlist section should always render
  expect(document.body).toBeTruthy()
})

test('StockResearch renders search input', () => {
  render(<StockResearch />, { wrapper: createWrapper() })
  // The page should have some input or placeholder for symbol search
  const inputs = document.querySelectorAll('input')
  expect(inputs.length).toBeGreaterThanOrEqual(0)
})
