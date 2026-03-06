import React from 'react'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import AnalysisPage from './Analysis'

// ── Silence EventSource (SSE not used in Analysis, but suppress jsdom warning) ──
global.EventSource = class {
  constructor() { this.close = vi.fn() }
}

// ── Mock KlineChart to avoid nested authFetch calls in Analysis tests ────────
vi.mock('../components/KlineChart', () => ({
  default: ({ symbol }) => <div data-testid="kline-chart" data-symbol={symbol}>KlineChart:{symbol}</div>
}))

// ── symbolNames mock — two variants controlled per-describe ─────────────────
const mockSymbolNames = vi.fn(() => ({ '2330': '台積電', '2412': '中華電' }))
const mockFormatSymbol = vi.fn((sym, names) => {
  const name = names?.[sym]
  return name ? `${sym} ${name}` : sym
})

vi.mock('../lib/symbolNames', () => ({
  useSymbolNames: () => mockSymbolNames(),
  formatSymbol: (sym, names) => mockFormatSymbol(sym, names),
}))

// ── Chips fixture ─────────────────────────────────────────────────────────────
const mockChipsData = {
  trade_date: '2026-03-03',
  data: [
    { symbol: '2330', name: '台積電', foreign_net: 550000, trust_net: 100000,
      dealer_net: 60000, total_net: 710000, margin_balance: 12000, short_balance: 500 },
    { symbol: '2412', name: '中華電', foreign_net: -200000, trust_net: -100000,
      dealer_net: 5000, total_net: -295000, margin_balance: 3000, short_balance: 200 },
  ],
}

// ── Fixtures ─────────────────────────────────────────────────────────────────
const mockReport = {
  trade_date: '2026-03-03',
  generated_at: Date.now(),
  market_summary: {
    sentiment: 'neutral',
    top_movers: [{ symbol: '2330', name: '台積電', close: 1000, change: 10, volume: 1000000 }],
    institution_flows: [
      { symbol: '2330', foreign_net: 500000000, investment_trust_net: -100000000, dealer_net: 50000000 },
    ],
  },
  technical: {
    '2330': { close: 1000, ma5: 990, ma20: 975, ma60: 950, rsi14: 55,
              macd: { macd: 5, signal: 4, histogram: 1 }, support: 960, resistance: 1020 },
    '2412': { close: 120, ma5: 118, ma20: 115, ma60: 110, rsi14: 62,
              macd: { macd: 1.5, signal: 1.2, histogram: 0.3 }, support: 112, resistance: 125 },
  },
  strategy: {
    summary: '整體中性',
    market_outlook: { sentiment: 'neutral', sector_focus: ['半導體', '電信'], confidence: 0.7 },
    position_actions: [
      { symbol: '2330', action: 'hold', reason: '趨勢向上' },
      { symbol: '2412', action: 'reduce', reason: '技術超買' },
    ],
    watchlist_opportunities: [
      { symbol: '2303', entry_condition: '突破壓力位', stop_loss: 45 },
    ],
    risk_notes: ['注意外資動向', '聯準會會議風險'],
  },
  model_used: 'gemini-2.5-flash',
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** URL-aware fetch mock: routes /api/chips/ to chips fixture, everything else to report. */
function makeDefaultFetchMock(report = mockReport, chipsData = mockChipsData) {
  return vi.fn().mockImplementation((url) => {
    if (String(url).includes('/api/chips/')) {
      return Promise.resolve({
        ok: true, status: 200,
        json: async () => chipsData,
      })
    }
    return Promise.resolve({ ok: true, status: 200, json: async () => report })
  })
}

/** Simple single-response mock (used for non-chips tests that override all URLs). */
function makeFetchMock(report = mockReport) {
  return vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => report })
}

function renderPage() {
  return render(<MemoryRouter><AnalysisPage /></MemoryRouter>)
}

async function renderAndLoad() {
  renderPage()
  await waitFor(() => screen.getByText(/2026-03-03/))
}

async function switchToTab(tabText) {
  const tabs = screen.queryAllByText(tabText)
  fireEvent.click(tabs[0])
}

// ── Setup / Teardown ──────────────────────────────────────────────────────────
beforeEach(() => {
  vi.clearAllMocks()
  global.fetch = makeDefaultFetchMock()
  mockSymbolNames.mockReturnValue({ '2330': '台積電', '2412': '中華電' })
})

afterEach(() => vi.clearAllMocks())

// ══════════════════════════════════════════════════════════════════════════════
// PAGE-LEVEL TESTS
// ══════════════════════════════════════════════════════════════════════════════
describe('AnalysisPage — page shell', () => {
  it('renders page title', () => {
    renderPage()
    expect(screen.getByText('盤後分析')).toBeTruthy()
  })

  it('shows loading indicator while fetching', () => {
    global.fetch = vi.fn(() => new Promise(() => {}))  // never resolves
    renderPage()
    expect(screen.getByText('讀取中…')).toBeTruthy()
  })

  it('shows 404 / no-data message when API returns 404', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) })
    renderPage()
    await waitFor(() => screen.getByText(/盤後分析尚未產生/))
  })

  it('shows error message on non-404 HTTP error', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({}) })
    renderPage()
    await waitFor(() => screen.getByText(/無法載入盤後分析/))
  })

  it('shows error message on network failure', async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error('Network error'))
    renderPage()
    await waitFor(() => screen.getByText(/無法載入盤後分析/))
  })

  it('displays trade date after load', async () => {
    await renderAndLoad()
    expect(screen.getByText(/2026-03-03/)).toBeTruthy()
  })

  it('renders four tabs', async () => {
    await renderAndLoad()
    expect(screen.queryAllByText('今日市場概覽').length).toBeGreaterThan(0)
    expect(screen.queryAllByText('個股技術分析').length).toBeGreaterThan(0)
    expect(screen.queryAllByText('法人籌碼').length).toBeGreaterThan(0)
    expect(screen.queryAllByText('AI 明日策略').length).toBeGreaterThan(0)
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// MARKET OVERVIEW TAB
// ══════════════════════════════════════════════════════════════════════════════
describe('MarketOverviewTab', () => {
  it('shows sentiment 中性', async () => {
    await renderAndLoad()
    expect(screen.getByText('中性')).toBeTruthy()
  })

  it('shows top mover symbol and name', async () => {
    await renderAndLoad()
    // Symbol in table
    expect(screen.queryAllByText('2330').length).toBeGreaterThan(0)
    expect(screen.getByText('台積電')).toBeTruthy()
  })

  it('shows institution flows table when data present', async () => {
    await renderAndLoad()
    expect(screen.getByText('三大法人流向（萬元）')).toBeTruthy()
  })

  it('shows bullish sentiment badge in emerald', async () => {
    const bullReport = { ...mockReport, market_summary: { ...mockReport.market_summary, sentiment: 'bullish' } }
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => bullReport })
    renderPage()
    await waitFor(() => screen.getByText('偏多'))
  })

  it('shows bearish sentiment badge in rose', async () => {
    const bearReport = { ...mockReport, market_summary: { ...mockReport.market_summary, sentiment: 'bearish' } }
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => bearReport })
    renderPage()
    await waitFor(() => screen.getByText('偏空'))
  })

  it('hides institution flows section when empty', async () => {
    const noFlows = { ...mockReport, market_summary: { ...mockReport.market_summary, institution_flows: [] } }
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => noFlows })
    renderPage()
    await waitFor(() => screen.getByText(/2026-03-03/))
    expect(screen.queryByText('三大法人流向（萬元）')).toBeNull()
  })

  it('shows unknown sentiment badge for unrecognised value', async () => {
    const unknownReport = { ...mockReport, market_summary: { ...mockReport.market_summary, sentiment: 'extreme_greed' } }
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => unknownReport })
    renderPage()
    await waitFor(() => screen.getByText('未知'))
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// TECHNICAL TAB — symbol names + K-line
// ══════════════════════════════════════════════════════════════════════════════
describe('TechnicalTab — stock names', () => {
  async function openTechnical() {
    await renderAndLoad()
    await switchToTab('個股技術分析')
  }

  it('shows formatted symbol with name when name is known', async () => {
    await openTechnical()
    await waitFor(() => screen.getByText('2330 台積電'))
  })

  it('shows second symbol with name', async () => {
    await openTechnical()
    await waitFor(() => screen.getByText('2412 中華電'))
  })

  it('falls back to raw symbol when name is not in names map', async () => {
    mockSymbolNames.mockReturnValue({})
    await openTechnical()
    await waitFor(() => screen.queryAllByText(/2330/).length > 0)
    // Raw symbol without name
    expect(screen.queryByText('2330 台積電')).toBeNull()
  })

  it('shows KlineChart for selected symbol', async () => {
    await openTechnical()
    await waitFor(() => screen.getByTestId('kline-chart'))
  })

  it('KlineChart receives correct symbol prop on initial selection', async () => {
    await openTechnical()
    await waitFor(() => {
      const chart = screen.getByTestId('kline-chart')
      expect(chart.dataset.symbol).toBe('2330')
    })
  })

  it('switches KlineChart symbol when different button is clicked', async () => {
    await openTechnical()
    await waitFor(() => screen.getByText('2412 中華電'))
    // Click 2412 button
    const btn2412 = screen.getAllByText('2412 中華電')[0]
    fireEvent.click(btn2412)
    await waitFor(() => {
      const chart = screen.getByTestId('kline-chart')
      expect(chart.dataset.symbol).toBe('2412')
    })
  })

  it('shows technical indicators for selected symbol', async () => {
    await openTechnical()
    await waitFor(() => screen.getByText('RSI14'))
    expect(screen.getByText('55.0')).toBeTruthy()
  })

  it('shows MA5, MA20, MA60 values', async () => {
    await openTechnical()
    await waitFor(() => screen.getByText('MA5'))
    expect(screen.getByText('990')).toBeTruthy()   // MA5
    expect(screen.getByText('975')).toBeTruthy()   // MA20
    expect(screen.getByText('950')).toBeTruthy()   // MA60
  })

  it('shows MACD and Signal values', async () => {
    await openTechnical()
    await waitFor(() => screen.getByText('MACD'))
    expect(screen.getByText('5.00')).toBeTruthy()   // MACD
    expect(screen.getByText('4.00')).toBeTruthy()   // Signal
  })

  it('shows support and resistance', async () => {
    await openTechnical()
    await waitFor(() => screen.getByText('支撐'))
    expect(screen.getByText('960')).toBeTruthy()
    expect(screen.getByText('1020')).toBeTruthy()
  })

  it('shows — for missing indicators', async () => {
    const sparseReport = {
      ...mockReport,
      technical: { '2330': { close: 100 } },
    }
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => sparseReport })
    renderPage()
    await waitFor(() => screen.getByText(/2026-03-03/))
    await switchToTab('個股技術分析')
    await waitFor(() => screen.getAllByText('—').length > 0)
    const dashes = screen.getAllByText('—')
    expect(dashes.length).toBeGreaterThan(0)
  })

  it('renders nothing in technical section when technical data is empty', async () => {
    const emptyTech = { ...mockReport, technical: {} }
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => emptyTech })
    renderPage()
    await waitFor(() => screen.getByText(/2026-03-03/))
    await switchToTab('個股技術分析')
    expect(screen.queryByTestId('kline-chart')).toBeNull()
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// STRATEGY TAB — symbol names
// ══════════════════════════════════════════════════════════════════════════════
describe('StrategyTab — stock names', () => {
  async function openStrategy() {
    await renderAndLoad()
    await switchToTab('AI 明日策略')
  }

  it('shows strategy summary', async () => {
    await openStrategy()
    await waitFor(() => screen.getByText('整體中性'))
  })

  it('shows sector_focus tags', async () => {
    await openStrategy()
    await waitFor(() => screen.getByText('半導體'))
    expect(screen.getByText('電信')).toBeTruthy()
  })

  it('shows position action symbol with name', async () => {
    await openStrategy()
    await waitFor(() => screen.getByText('2330 台積電'))
  })

  it('shows second position action symbol with name', async () => {
    await openStrategy()
    await waitFor(() => screen.getByText('2412 中華電'))
  })

  it('shows action badge (hold)', async () => {
    await openStrategy()
    await waitFor(() => screen.getByText('hold'))
  })

  it('shows action badge (reduce)', async () => {
    await openStrategy()
    await waitFor(() => screen.getByText('reduce'))
  })

  it('shows position action reason', async () => {
    await openStrategy()
    await waitFor(() => screen.getByText('趨勢向上'))
  })

  it('shows watchlist opportunity — symbol falls back to raw when name unknown', async () => {
    // 2303 is not in mock names
    await openStrategy()
    await waitFor(() => screen.getByText('突破壓力位'))
    // 2303 has no name in mockSymbolNames → shows raw '2303'
    expect(screen.queryAllByText(/2303/).length).toBeGreaterThan(0)
  })

  it('shows watchlist stop loss value', async () => {
    await openStrategy()
    await waitFor(() => screen.getByText(/Stop loss: 45/))
  })

  it('shows risk notes', async () => {
    await openStrategy()
    await waitFor(() => screen.getByText('注意外資動向'))
    expect(screen.getByText('聯準會會議風險')).toBeTruthy()
  })

  it('hides position actions panel when empty', async () => {
    const noActions = { ...mockReport, strategy: { ...mockReport.strategy, position_actions: [] } }
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => noActions })
    renderPage()
    await waitFor(() => screen.getByText(/2026-03-03/))
    await switchToTab('AI 明日策略')
    expect(screen.queryByText('持倉操作建議')).toBeNull()
  })

  it('hides watchlist panel when empty', async () => {
    const noWatchlist = { ...mockReport, strategy: { ...mockReport.strategy, watchlist_opportunities: [] } }
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => noWatchlist })
    renderPage()
    await waitFor(() => screen.getByText(/2026-03-03/))
    await switchToTab('AI 明日策略')
    expect(screen.queryByText('觀察名單機會')).toBeNull()
  })

  it('hides risk notes panel when empty', async () => {
    const noRisks = { ...mockReport, strategy: { ...mockReport.strategy, risk_notes: [] } }
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => noRisks })
    renderPage()
    await waitFor(() => screen.getByText(/2026-03-03/))
    await switchToTab('AI 明日策略')
    expect(screen.queryByText('風險注意事項')).toBeNull()
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// BOUNDARY TESTS
// ══════════════════════════════════════════════════════════════════════════════
describe('Boundary cases', () => {
  it('handles report with null market_summary gracefully', async () => {
    const nullSummary = { ...mockReport, market_summary: null }
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => nullSummary })
    renderPage()
    await waitFor(() => screen.getByText(/2026-03-03/))
    // Should render without crash; SentimentBadge shows '未知'
    expect(screen.getByText('未知')).toBeTruthy()
  })

  it('handles report with null technical gracefully', async () => {
    const nullTech = { ...mockReport, technical: null }
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => nullTech })
    renderPage()
    await waitFor(() => screen.getByText(/2026-03-03/))
    await switchToTab('個股技術分析')
    // No crash, no chart rendered
    expect(screen.queryByTestId('kline-chart')).toBeNull()
  })

  it('handles report with null strategy gracefully', async () => {
    const nullStrategy = { ...mockReport, strategy: null }
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => nullStrategy })
    renderPage()
    await waitFor(() => screen.getByText(/2026-03-03/))
    await switchToTab('AI 明日策略')
    // No crash; summary shows '—'
    expect(screen.queryAllByText('—').length).toBeGreaterThanOrEqual(1)
  })

  it('handles useSymbolNames returning null gracefully', async () => {
    mockSymbolNames.mockReturnValue(null)
    renderPage()
    await waitFor(() => screen.getByText(/2026-03-03/))
    await switchToTab('個股技術分析')
    // formatSymbol(sym, null) → should return raw sym without crashing
    expect(screen.queryAllByText(/2330/).length).toBeGreaterThan(0)
  })

  it('handles top_movers with missing optional fields', async () => {
    const sparseMovers = {
      ...mockReport,
      market_summary: {
        ...mockReport.market_summary,
        top_movers: [{ symbol: '9999', name: null, close: null, change: null }],
      },
    }
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => sparseMovers })
    renderPage()
    await waitFor(() => screen.getByText(/2026-03-03/))
    // Should render without crash
    expect(screen.queryAllByText('9999').length).toBeGreaterThan(0)
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// CHIPS TAB TESTS
// ══════════════════════════════════════════════════════════════════════════════
describe('ChipsTab — 法人籌碼', () => {
  async function openChips() {
    await renderAndLoad()
    await switchToTab('法人籌碼')
  }

  // ── Loading state ────────────────────────────────────────────────────────
  it('shows loading state while chips data is fetching', async () => {
    global.fetch = vi.fn().mockImplementation((url) => {
      if (String(url).includes('/api/chips/')) return new Promise(() => {})  // never resolves
      return Promise.resolve({ ok: true, status: 200, json: async () => mockReport })
    })
    renderPage()
    await waitFor(() => screen.getByText(/2026-03-03/))
    await switchToTab('法人籌碼')
    expect(screen.getByText('讀取籌碼資料中…')).toBeTruthy()
  })

  // ── No data (404) ────────────────────────────────────────────────────────
  it('shows no-data message when API returns 404', async () => {
    global.fetch = vi.fn().mockImplementation((url) => {
      if (String(url).includes('/api/chips/')) {
        return Promise.resolve({ ok: false, status: 404, json: async () => ({}) })
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => mockReport })
    })
    await renderAndLoad()
    await switchToTab('法人籌碼')
    await waitFor(() => screen.getByText(/本日尚無法人籌碼資料/))
  })

  // ── Error state ──────────────────────────────────────────────────────────
  it('shows error message when chips fetch fails with 500', async () => {
    global.fetch = vi.fn().mockImplementation((url) => {
      if (String(url).includes('/api/chips/')) {
        return Promise.resolve({ ok: false, status: 500, json: async () => ({}) })
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => mockReport })
    })
    await renderAndLoad()
    await switchToTab('法人籌碼')
    await waitFor(() => screen.getByText(/無法載入籌碼資料/))
  })

  it('shows error message when chips fetch network error', async () => {
    global.fetch = vi.fn().mockImplementation((url) => {
      if (String(url).includes('/api/chips/'))
        return Promise.reject(new Error('Network error'))
      return Promise.resolve({ ok: true, status: 200, json: async () => mockReport })
    })
    await renderAndLoad()
    await switchToTab('法人籌碼')
    await waitFor(() => screen.getByText(/無法載入籌碼資料/))
  })

  // ── Normal rendering ─────────────────────────────────────────────────────
  it('shows institution flows panel', async () => {
    await openChips()
    await waitFor(() => screen.getByText('三大法人買賣超（萬股）'))
  })

  it('shows column headers: 外資, 投信, 自營, 合計', async () => {
    await openChips()
    await waitFor(() => screen.getByText('外資'))
    expect(screen.getByText('投信')).toBeTruthy()
    expect(screen.getByText('自營')).toBeTruthy()
    expect(screen.getByText('合計')).toBeTruthy()
  })

  it('shows symbol with name in chips table', async () => {
    await openChips()
    await waitFor(() => screen.queryAllByText('2330 台積電').length > 0)
    expect(screen.queryAllByText('2330 台積電').length).toBeGreaterThan(0)
  })

  it('shows second symbol with name', async () => {
    await openChips()
    await waitFor(() => screen.queryAllByText('2412 中華電').length > 0)
  })

  it('formats total_net as 萬股 (710000 → "71.0")', async () => {
    await openChips()
    await waitFor(() => screen.getByText('71.0'))  // 710000 / 10000 = 71.0
  })

  it('shows negative total_net correctly (-295000 → "-29.5")', async () => {
    await openChips()
    await waitFor(() => screen.getByText('-29.5'))  // -295000 / 10000 = -29.5
  })

  // ── Margin panel ─────────────────────────────────────────────────────────
  it('shows margin balance panel when data has margin_balance', async () => {
    await openChips()
    await waitFor(() => screen.getByText('融資借券餘額（張）'))
  })

  it('shows margin balance values', async () => {
    await openChips()
    await waitFor(() => screen.getByText('12,000'))  // 12000.toLocaleString()
  })

  it('hides margin panel when all margin_balance are null', async () => {
    const noMarginData = {
      ...mockChipsData,
      data: mockChipsData.data.map(r => ({ ...r, margin_balance: null, short_balance: null })),
    }
    global.fetch = vi.fn().mockImplementation((url) => {
      if (String(url).includes('/api/chips/'))
        return Promise.resolve({ ok: true, status: 200, json: async () => noMarginData })
      return Promise.resolve({ ok: true, status: 200, json: async () => mockReport })
    })
    await renderAndLoad()
    await switchToTab('法人籌碼')
    await waitFor(() => screen.getByText('三大法人買賣超（萬股）'))
    expect(screen.queryByText('融資借券餘額（張）')).toBeNull()
  })

  // ── Empty data ────────────────────────────────────────────────────────────
  it('shows no-data message when chips data array is empty', async () => {
    global.fetch = vi.fn().mockImplementation((url) => {
      if (String(url).includes('/api/chips/'))
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ trade_date: '2026-03-03', data: [] }) })
      return Promise.resolve({ ok: true, status: 200, json: async () => mockReport })
    })
    await renderAndLoad()
    await switchToTab('法人籌碼')
    await waitFor(() => screen.getByText(/本日尚無法人籌碼資料/))
  })

  // ── Symbol name fallback ─────────────────────────────────────────────────
  it('falls back to raw symbol when name not found in names map', async () => {
    mockSymbolNames.mockReturnValue({})  // empty names
    await openChips()
    // With empty names, formatSymbol returns just '2330', not '2330 台積電'
    await waitFor(() => screen.queryAllByText('2330').length > 0)
    expect(screen.queryByText('2330 台積電')).toBeNull()
  })
})
