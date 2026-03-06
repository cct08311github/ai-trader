import React from 'react'
import { render, screen, waitFor, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import KlineChart from './KlineChart'

// ── Mock auth ───────────────────────────────────────────────────────────────
vi.mock('../lib/auth', () => ({
  authFetch: vi.fn(),
  getApiBase: vi.fn(() => ''),
}))

import { authFetch, getApiBase } from '../lib/auth'

// ── Sample data ─────────────────────────────────────────────────────────────
const upCandle   = { trade_date: '2026-01-02', open: 100, high: 110, low:  95, close: 108, volume: 1000 }
const downCandle = { trade_date: '2026-01-03', open: 108, high: 112, low:  98, close: 102, volume: 1500 }
const flatCandle = { trade_date: '2026-01-04', open: 102, high: 102, low: 102, close: 102, volume:    0 }

const multipleCandles = [
  { trade_date: '2026-01-01', open:  90, high: 105, low:  88, close: 100, volume: 2000 },
  upCandle,
  downCandle,
  { trade_date: '2026-01-05', open: 102, high: 115, low: 100, close: 112, volume: 1800 },
  { trade_date: '2026-01-06', open: 112, high: 118, low: 108, close: 109, volume: 900  },
]

function makeOkResponse(data) {
  return Promise.resolve({ json: () => Promise.resolve({ data }) })
}

function makeOkResponseNoDataKey() {
  return Promise.resolve({ json: () => Promise.resolve({}) })
}

// ── Setup ────────────────────────────────────────────────────────────────────
beforeEach(() => {
  vi.clearAllMocks()
})

// ── Tests ────────────────────────────────────────────────────────────────────

describe('KlineChart — loading state', () => {
  it('shows spinner while fetch is pending', () => {
    // Never-resolving promise keeps the component in loading state
    authFetch.mockReturnValue(new Promise(() => {}))
    const { container } = render(<KlineChart symbol="2330" />)
    // Spinner is the lucide RefreshCw; check the svg or a spinning element exists
    expect(container.querySelector('svg')).toBeTruthy()
  })

  it('does NOT fetch when symbol is null', () => {
    render(<KlineChart symbol={null} />)
    expect(authFetch).not.toHaveBeenCalled()
  })

  it('does NOT fetch when symbol is undefined', () => {
    render(<KlineChart />)
    expect(authFetch).not.toHaveBeenCalled()
  })
})

describe('KlineChart — empty / error states', () => {
  it('shows empty message when data is empty array', async () => {
    authFetch.mockReturnValue(makeOkResponse([]))
    render(<KlineChart symbol="2330" />)
    await waitFor(() => screen.getByText('無 K 線歷史資料'))
  })

  it('shows empty message when API returns no data key', async () => {
    authFetch.mockReturnValue(makeOkResponseNoDataKey())
    render(<KlineChart symbol="2330" />)
    await waitFor(() => screen.getByText('無 K 線歷史資料'))
  })

  it('shows empty message when fetch rejects (network error)', async () => {
    authFetch.mockReturnValue(Promise.reject(new Error('Network error')))
    render(<KlineChart symbol="2330" />)
    await waitFor(() => screen.getByText('無 K 線歷史資料'))
  })

  it('shows empty message when fetch rejects with non-Error value', async () => {
    // authFetch may reject with a string or null in edge cases
    authFetch.mockReturnValue(Promise.reject('timeout'))
    render(<KlineChart symbol="2330" />)
    await waitFor(() => screen.getByText('無 K 線歷史資料'))
  })
})

describe('KlineChart — normal rendering with data', () => {
  it('renders SVG chart with multiple candles', async () => {
    authFetch.mockReturnValue(makeOkResponse(multipleCandles))
    const { container } = render(<KlineChart symbol="2330" />)
    await waitFor(() => screen.getByText('K 線圖（日線）'))
    // SVG should be present
    expect(container.querySelector('svg')).toBeTruthy()
  })

  it('displays date range header', async () => {
    authFetch.mockReturnValue(makeOkResponse(multipleCandles))
    render(<KlineChart symbol="2330" />)
    await waitFor(() => screen.getByText(/2026-01-01.*2026-01-06/))
  })

  it('renders candle rectangles for each data point', async () => {
    authFetch.mockReturnValue(makeOkResponse(multipleCandles))
    const { container } = render(<KlineChart symbol="2330" />)
    await waitFor(() => screen.getByText('K 線圖（日線）'))
    // Each candle has body rect + volume rect = 2 rects per candle, plus potential others
    const rects = container.querySelectorAll('rect')
    expect(rects.length).toBeGreaterThanOrEqual(multipleCandles.length)
  })

  it('renders wick lines for each candle', async () => {
    authFetch.mockReturnValue(makeOkResponse(multipleCandles))
    const { container } = render(<KlineChart symbol="2330" />)
    await waitFor(() => screen.getByText('K 線圖（日線）'))
    const lines = container.querySelectorAll('line')
    // At minimum: candle wicks (1 per candle) + grid lines + separator
    expect(lines.length).toBeGreaterThanOrEqual(multipleCandles.length)
  })
})

describe('KlineChart — single candle edge case', () => {
  it('renders correctly with a single candle', async () => {
    authFetch.mockReturnValue(makeOkResponse([upCandle]))
    const { container } = render(<KlineChart symbol="2330" />)
    await waitFor(() => screen.getByText('K 線圖（日線）'))
    expect(container.querySelector('svg')).toBeTruthy()
    expect(screen.getByText(/2026-01-02/)).toBeTruthy()
  })
})

describe('KlineChart — flat candle edge case (open === close)', () => {
  it('does not crash when open equals close (flat candle)', async () => {
    authFetch.mockReturnValue(makeOkResponse([upCandle, flatCandle, downCandle]))
    const { container } = render(<KlineChart symbol="2330" />)
    await waitFor(() => screen.getByText('K 線圖（日線）'))
    expect(container.querySelector('svg')).toBeTruthy()
  })
})

describe('KlineChart — URL construction', () => {
  it('calls correct endpoint with default days=60', async () => {
    authFetch.mockReturnValue(makeOkResponse([]))
    render(<KlineChart symbol="2330" />)
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/portfolio/kline/2330')
    ))
    expect(authFetch.mock.calls[0][0]).toContain('days=60')
  })

  it('passes custom days prop to URL', async () => {
    authFetch.mockReturnValue(makeOkResponse([]))
    render(<KlineChart symbol="2330" days={30} />)
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith(
      expect.stringContaining('days=30')
    ))
  })

  it('URL-encodes symbol with special characters', async () => {
    authFetch.mockReturnValue(makeOkResponse([]))
    render(<KlineChart symbol="2330 T" />)
    await waitFor(() => expect(authFetch).toHaveBeenCalled())
    const url = authFetch.mock.calls[0][0]
    expect(url).toContain('2330')
    expect(url).not.toContain(' ')  // space must be encoded
  })

  it('prepends getApiBase() to URL', async () => {
    getApiBase.mockReturnValue('https://api.example.com')
    authFetch.mockReturnValue(makeOkResponse([]))
    render(<KlineChart symbol="2330" />)
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith(
      expect.stringContaining('https://api.example.com')
    ))
  })
})

describe('KlineChart — re-fetch on prop change', () => {
  it('fetches again when symbol changes', async () => {
    authFetch.mockReturnValue(makeOkResponse([]))
    const { rerender } = render(<KlineChart symbol="2330" />)
    await waitFor(() => expect(authFetch).toHaveBeenCalledTimes(1))

    rerender(<KlineChart symbol="2412" />)
    await waitFor(() => expect(authFetch).toHaveBeenCalledTimes(2))
    expect(authFetch.mock.calls[1][0]).toContain('2412')
  })

  it('fetches again when days changes', async () => {
    authFetch.mockReturnValue(makeOkResponse([]))
    const { rerender } = render(<KlineChart symbol="2330" days={60} />)
    await waitFor(() => expect(authFetch).toHaveBeenCalledTimes(1))

    rerender(<KlineChart symbol="2330" days={30} />)
    await waitFor(() => expect(authFetch).toHaveBeenCalledTimes(2))
    expect(authFetch.mock.calls[1][0]).toContain('days=30')
  })
})

describe('KlineChart — candle color logic', () => {
  it('up candle (close >= open) uses green', async () => {
    authFetch.mockReturnValue(makeOkResponse([upCandle]))
    const { container } = render(<KlineChart symbol="2330" />)
    await waitFor(() => screen.getByText('K 線圖（日線）'))
    // Green emerald color: #10b981
    const rects = Array.from(container.querySelectorAll('rect'))
    const greenRects = rects.filter(r => r.getAttribute('fill') === '#10b981')
    expect(greenRects.length).toBeGreaterThan(0)
  })

  it('down candle (close < open) uses red', async () => {
    authFetch.mockReturnValue(makeOkResponse([downCandle]))
    const { container } = render(<KlineChart symbol="2330" />)
    await waitFor(() => screen.getByText('K 線圖（日線）'))
    // Red rose color: #f43f5e
    const rects = Array.from(container.querySelectorAll('rect'))
    const redRects = rects.filter(r => r.getAttribute('fill') === '#f43f5e')
    expect(redRects.length).toBeGreaterThan(0)
  })

  it('zero-volume candle renders without crash (min height=1)', async () => {
    const zeroVolCandle = { ...upCandle, volume: 0 }
    authFetch.mockReturnValue(makeOkResponse([zeroVolCandle]))
    const { container } = render(<KlineChart symbol="2330" />)
    await waitFor(() => screen.getByText('K 線圖（日線）'))
    expect(container.querySelector('svg')).toBeTruthy()
  })
})

describe('KlineChart — all-same-price edge case', () => {
  it('does not throw when all OHLC values are identical', async () => {
    const allSame = [
      { trade_date: '2026-01-01', open: 100, high: 100, low: 100, close: 100, volume: 500 },
      { trade_date: '2026-01-02', open: 100, high: 100, low: 100, close: 100, volume: 500 },
    ]
    authFetch.mockReturnValue(makeOkResponse(allSame))
    // Should render without throwing even with NaN coords from 0/0 division
    expect(() => render(<KlineChart symbol="2330" />)).not.toThrow()
  })
})
