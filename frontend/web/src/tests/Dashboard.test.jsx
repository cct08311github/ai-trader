import React from 'react'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import Dashboard from '../pages/Dashboard'

// Suppress ResizeObserver / canvas warnings in jsdom
global.HTMLCanvasElement.prototype.getContext = () => null

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return ({ children }) => (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        {children}
      </MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  // Mock all API calls to return empty-but-valid responses
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({}),
  })
})

afterEach(() => vi.clearAllMocks())

test('Dashboard renders without crash', () => {
  render(<Dashboard />, { wrapper: createWrapper() })
  // "投組總值" KPI label is always rendered
  const labels = screen.getAllByText(/投組總值/i)
  expect(labels.length).toBeGreaterThan(0)
})

test('Dashboard shows portfolio KPI tile label', () => {
  render(<Dashboard />, { wrapper: createWrapper() })
  expect(screen.getByText(/投組總值/i)).toBeInTheDocument()
})

test('Dashboard shows accessibility live region', () => {
  render(<Dashboard />, { wrapper: createWrapper() })
  const live = document.querySelector('[aria-live="polite"]')
  expect(live).toBeTruthy()
})
