import React from 'react'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import Geopolitical from '../pages/Geopolitical'

global.HTMLCanvasElement.prototype.getContext = () => null

// Mock react-simple-maps to avoid SVG world map complexity
vi.mock('react-simple-maps', () => ({
  ComposableMap: ({ children }) => <div data-testid="world-map">{children}</div>,
  Geographies: ({ children }) => children({ geographies: [] }),
  Geography: () => null,
  Marker: ({ children }) => <g>{children}</g>,
  ZoomableGroup: ({ children }) => <g>{children}</g>,
}))

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
    json: async () => ({ events: [] }),
  })
})

afterEach(() => vi.clearAllMocks())

test('Geopolitical page renders without crash', () => {
  render(<Geopolitical />, { wrapper: createWrapper() })
  expect(screen.getByText(/地緣政治分析/i)).toBeInTheDocument()
})
