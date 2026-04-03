import React from 'react'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import Reports from '../pages/Reports'

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
    json: async () => ({ reports: [] }),
  })
})

afterEach(() => vi.clearAllMocks())

test('Reports page renders without crash', () => {
  render(<Reports />, { wrapper: createWrapper() })
  expect(screen.getByText(/研究報告/i)).toBeInTheDocument()
})
