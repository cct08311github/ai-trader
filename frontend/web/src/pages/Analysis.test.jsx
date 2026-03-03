import React from 'react'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import AnalysisPage from './Analysis'

global.EventSource = class {
  constructor() { this.close = vi.fn() }
}

const mockReport = {
  trade_date: '2026-03-03',
  generated_at: Date.now(),
  market_summary: {
    sentiment: 'neutral',
    top_movers: [{ symbol: '2330', name: '台積電', close: 1000, change: 10, volume: 1000000 }],
    institution_flows: [],
  },
  technical: {
    '2330': { close: 1000, ma5: 990, ma20: 975, ma60: 950, rsi14: 55,
              macd: { macd: 5, signal: 4, histogram: 1 }, support: 960, resistance: 1020 }
  },
  strategy: {
    summary: '整體中性',
    market_outlook: { sentiment: 'neutral', sector_focus: ['半導體'], confidence: 0.7 },
    position_actions: [{ symbol: '2330', action: 'hold', reason: '趨勢向上' }],
    watchlist_opportunities: [],
    risk_notes: ['注意外資動向'],
  },
  model_used: 'gemini-2.5-flash',
}

beforeEach(() => {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => mockReport,
  })
})

afterEach(() => vi.clearAllMocks())

function renderPage() {
  return render(
    <MemoryRouter>
      <AnalysisPage />
    </MemoryRouter>
  )
}

test('顯示盤後分析標題', async () => {
  renderPage()
  expect(screen.getByText('盤後分析')).toBeTruthy()
})

test('載入完成後顯示日期', async () => {
  renderPage()
  await waitFor(() => screen.getByText(/2026-03-03/))
})

test('Tab 切換：個股技術分析', async () => {
  renderPage()
  await waitFor(() => screen.getByText(/2026-03-03/))
  const tabs = screen.queryAllByText('個股技術分析')
  fireEvent.click(tabs[0])
  await waitFor(() => screen.getByText('2330'))
})

test('Tab 切換：AI 明日策略', async () => {
  renderPage()
  await waitFor(() => screen.getByText(/2026-03-03/))
  const tabs = screen.queryAllByText('AI 明日策略')
  fireEvent.click(tabs[0])
  await waitFor(() => screen.getByText('整體中性'))
})

test('fetch 失敗時顯示錯誤訊息', async () => {
  global.fetch = vi.fn().mockRejectedValue(new Error('Network error'))
  renderPage()
  await waitFor(() => screen.getByText(/無法載入|error/i))
})
