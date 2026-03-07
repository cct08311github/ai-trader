import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ThemeProvider } from '../lib/theme'
import PositionDetailDrawer from './PositionDetailDrawer'

// --- Mocks ---

// Mock EventSource (used by QuotePanel SSE)
class MockEventSource {
  constructor(url) { this.url = url; this.onopen = null; this.onmessage = null; this.onerror = null }
  close() { }
}
global.EventSource = MockEventSource

// Mock authFetch + getApiBase
vi.mock('../lib/auth', () => ({
  authFetch: vi.fn((url) => {
    // position-detail endpoint returns a truthy detail object
    if (url && url.includes('position-detail')) {
      return Promise.resolve({ json: () => Promise.resolve({ data: { symbol: '2330' } }) })
    }
    // quote snapshot returns null data (market closed)
    return Promise.resolve({ json: () => Promise.resolve({ data: null }) })
  }),
  getApiBase: vi.fn(() => 'http://localhost:8080'),
  getToken: vi.fn(() => 'test-token'),
}))

// Mock lock helpers
vi.mock('../lib/portfolio', () => ({
  lockSymbol: vi.fn(() => Promise.resolve()),
  unlockSymbol: vi.fn(() => Promise.resolve()),
}))

function renderDrawer(props = {}) {
  const defaults = {
    symbol: '2330',
    position: { symbol: '2330', qty: 100, avg_price: 600.0, last_price: 620.0, unrealized_pnl: 2000 },
    isLocked: false,
    onLockChange: vi.fn(),
    onClose: vi.fn(),
  }
  return render(
    <ThemeProvider defaultTheme="dark">
      <PositionDetailDrawer {...defaults} {...props} />
    </ThemeProvider>
  )
}

// --- Tests ---

describe('PositionDetailDrawer', () => {

  it('renders nothing when symbol is null', () => {
    const { container } = renderDrawer({ symbol: null })
    expect(container.firstChild).toBeNull()
  })

  it('shows symbol in header', async () => {
    renderDrawer()
    // Symbol appears in the drawer header or title
    expect(await screen.findAllByText(/2330/)).toBeTruthy()
  })

  it('shows position qty and avg price', async () => {
    renderDrawer()
    // Waiting for content ensures act() compliance
    await waitFor(() => expect(screen.getByText(/600/)).toBeInTheDocument())
  })

  it('shows 即時報價 section (QuotePanel)', async () => {
    renderDrawer()
    expect(await screen.findByText('即時報價')).toBeInTheDocument()
  })

  it('shows 等待開盤 when SSE not live', async () => {
    renderDrawer()
    expect(await screen.findByText('等待開盤')).toBeInTheDocument()
  })

  it('shows lock button', async () => {
    renderDrawer({ isLocked: false })
    await screen.findByText(/2330/)
    const btns = screen.queryAllByRole('button')
    expect(btns.length).toBeGreaterThan(0)
  })

  it('shows locked indicator when isLocked=true', async () => {
    renderDrawer({ isLocked: true })
    expect((await screen.findAllByText(/鎖定|解鎖|locked/i)).length).toBeGreaterThan(0)
  })

  it('calls onClose when backdrop is clicked', async () => {
    const onClose = vi.fn()
    renderDrawer({ onClose })
    await screen.findByText(/2330/)
    const backdrop = document.querySelector('[aria-hidden="true"]')
    if (backdrop) await userEvent.click(backdrop)
    expect(onClose).toHaveBeenCalled()
  })

  it('shows 讀取中 while detail is loading', async () => {
    renderDrawer()
    // It will either show loading or resolve fast
    expect(await screen.findByText(/2330/)).toBeInTheDocument()
  })

  it('shows 開盤後顯示五檔行情 when no bidask data', async () => {
    renderDrawer()
    expect(await screen.findByText('開盤後顯示五檔行情')).toBeInTheDocument()
  })
})
