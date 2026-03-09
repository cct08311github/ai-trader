import React from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

const mockFetchPmHistory = vi.fn()

vi.mock('../lib/pmApi', () => ({
  fetchPmHistory: (...args) => mockFetchPmHistory(...args),
}))

import PmReviewHistoryPanel from './PmReviewHistoryPanel'

describe('PmReviewHistoryPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders empty state when no reviews', async () => {
    mockFetchPmHistory.mockResolvedValue({
      data: [],
      pagination: { total: 0, limit: 10, offset: 0 },
    })
    render(<PmReviewHistoryPanel />)
    await waitFor(() => {
      expect(screen.getByText('尚無審核紀錄')).toBeInTheDocument()
    })
  })

  it('renders review records', async () => {
    mockFetchPmHistory.mockResolvedValue({
      data: [
        {
          review_id: 'pm_2026-03-09_abc',
          review_date: '2026-03-09',
          approved: 1,
          confidence: 0.85,
          source: 'llm',
          reason: 'Market bullish',
          recommended_action: 'BUY',
          bull_case: 'Strong earnings',
          bear_case: 'Inflation risk',
          neutral_case: '',
          consensus_points: '["Growth"]',
          divergence_points: '[]',
          reviewed_at: 1741478400000,
        },
      ],
      pagination: { total: 1, limit: 10, offset: 0 },
    })

    render(<PmReviewHistoryPanel />)

    await waitFor(() => {
      expect(screen.getByText('2026-03-09')).toBeInTheDocument()
    })
    expect(screen.getByText('授權')).toBeInTheDocument()
    expect(screen.getByText('LLM')).toBeInTheDocument()
    expect(screen.getByText('(1 筆)')).toBeInTheDocument()
  })

  it('expands review to show details', async () => {
    mockFetchPmHistory.mockResolvedValue({
      data: [
        {
          review_id: 'pm_2026-03-09_abc',
          review_date: '2026-03-09',
          approved: 0,
          confidence: 0.4,
          source: 'manual',
          reason: '市場不穩定',
          recommended_action: '觀望',
          bull_case: '',
          bear_case: '下行風險',
          neutral_case: '',
          consensus_points: '[]',
          divergence_points: '[]',
          reviewed_at: 1741478400000,
        },
      ],
      pagination: { total: 1, limit: 10, offset: 0 },
    })

    render(<PmReviewHistoryPanel />)

    await waitFor(() => {
      expect(screen.getByText('2026-03-09')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('2026-03-09').closest('button'))

    expect(screen.getByText('市場不穩定', { exact: false })).toBeInTheDocument()
    expect(screen.getByText('下行風險')).toBeInTheDocument()
  })

  it('shows loading text initially', () => {
    mockFetchPmHistory.mockReturnValue(new Promise(() => {}))
    render(<PmReviewHistoryPanel />)
    expect(screen.getByText('讀取中…')).toBeInTheDocument()
  })

  it('renders rejected review with correct styling', async () => {
    mockFetchPmHistory.mockResolvedValue({
      data: [
        {
          review_id: 'pm_2026-03-08_def',
          review_date: '2026-03-08',
          approved: 0,
          confidence: 0.3,
          source: 'llm',
          reason: 'Bear outlook',
          reviewed_at: 1741392000000,
        },
      ],
      pagination: { total: 1, limit: 10, offset: 0 },
    })

    render(<PmReviewHistoryPanel />)

    await waitFor(() => {
      expect(screen.getByText('封鎖')).toBeInTheDocument()
    })
  })
})
