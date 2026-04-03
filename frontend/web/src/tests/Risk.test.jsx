import React from 'react'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import Risk from '../pages/Risk'

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
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({}),
  })
})

afterEach(() => vi.clearAllMocks())

test('Risk page renders without crash', () => {
  render(<Risk />, { wrapper: createWrapper() })
  expect(screen.getByText(/風險管理/i)).toBeInTheDocument()
})
