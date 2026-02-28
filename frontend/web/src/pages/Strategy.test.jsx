import React from 'react'
import { describe, expect, it, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import StrategyPage from './Strategy'

class MockEventSource {
  constructor() {
    this.listeners = {}
  }
  addEventListener(name, cb) {
    this.listeners[name] = this.listeners[name] || []
    this.listeners[name].push(cb)
  }
  close() {}
}

beforeEach(() => {
  global.EventSource = MockEventSource

  global.fetch = vi.fn(async url => {
    const u = String(url)
    if (u.includes('/api/strategy/proposals')) {
      return {
        ok: true,
        json: async () => ({ status: 'ok', data: [], limit: 200, offset: 0 })
      }
    }
    if (u.includes('/api/strategy/logs')) {
      return {
        ok: true,
        json: async () => ({ status: 'ok', data: [], limit: 200, offset: 0 })
      }
    }
    return { ok: false, status: 404, json: async () => ({ detail: 'not found' }) }
  })
})

describe('StrategyPage', () => {
  it('renders proposal table and empty state', async () => {
    render(<StrategyPage />)

    expect(await screen.findByText('策略執行模組')).toBeTruthy()
    expect(await screen.findByText('目前沒有策略提案')).toBeTruthy()

    // headers
    expect(screen.getByText('時間')).toBeTruthy()
    expect(screen.getByText('ID')).toBeTruthy()
    expect(screen.getByText('狀態')).toBeTruthy()
  })
})
