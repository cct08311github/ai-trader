import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import LogTerminal from './LogTerminal'

// --- Mocks ---

// Mock EventSource (SSE connection)
class MockEventSource {
  constructor(url) {
    this.url = url
    this.listeners = {}
  }
  addEventListener(event, cb) {
    this.listeners[event] = cb
  }
  close() {}
}
global.EventSource = MockEventSource

vi.mock('../lib/auth', () => ({
  getToken: vi.fn(() => null),
}))

// --- Tests ---

describe('LogTerminal', () => {

  it('renders without crashing', () => {
    render(<LogTerminal />)
    expect(screen.getByText(/即時日誌終端機/)).toBeInTheDocument()
  })

  it('shows 未連線 initially (EventSource not yet opened)', () => {
    render(<LogTerminal />)
    expect(screen.getByText('未連線')).toBeInTheDocument()
  })

  it('shows SSE API endpoint URL', () => {
    render(<LogTerminal />)
    expect(screen.getByText(/api\/stream\/logs/)).toBeInTheDocument()
  })

  it('shows 尚無日誌 when log list is empty', () => {
    render(<LogTerminal />)
    expect(screen.getByText(/尚無日誌/)).toBeInTheDocument()
  })

  it('renders pause and clear buttons', () => {
    render(<LogTerminal />)
    expect(screen.getByText(/暫停/)).toBeInTheDocument()
    expect(screen.getByText('清除')).toBeInTheDocument()
  })

  it('renders level filter dropdown with ALL option', () => {
    render(<LogTerminal />)
    const select = document.querySelector('select')
    expect(select).toBeTruthy()
    expect(select.value).toBe('ALL')
  })

  it('renders search input', () => {
    render(<LogTerminal />)
    const input = document.querySelector('input[type="text"], input:not([type])')
    expect(input).toBeTruthy()
    expect(input.placeholder).toMatch(/搜尋/)
  })
})
