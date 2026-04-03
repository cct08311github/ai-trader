import React from 'react'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import Screener from '../pages/research/Screener'

global.HTMLCanvasElement.prototype.getContext = () => ({
  clearRect: () => {},
  beginPath: () => {},
  moveTo: () => {},
  lineTo: () => {},
  arc: () => {},
  fill: () => {},
  stroke: () => {},
  get strokeStyle() { return '' },
  set strokeStyle(_) {},
  get fillStyle() { return '' },
  set fillStyle(_) {},
  get lineWidth() { return 1 },
  set lineWidth(_) {},
})

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
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ data: [] }),
  })
})

afterEach(() => vi.clearAllMocks())

test('Screener renders without crash', () => {
  render(<Screener />, { wrapper: createWrapper() })
  expect(screen.getByText(/市場選股器/i)).toBeInTheDocument()
})

test('Screener renders filter bar', () => {
  render(<Screener />, { wrapper: createWrapper() })
  expect(screen.getByText(/條件篩選/i)).toBeInTheDocument()
})
