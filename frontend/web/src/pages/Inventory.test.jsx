import React from 'react'
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import InventoryPage from './Inventory'

describe('InventoryPage', () => {
  it('renders inventory dashboard title', () => {
    render(<InventoryPage />)
    expect(screen.getByText(/庫存總覽/i)).toBeDefined()
  })

  it('shows loading state initially', () => {
    render(<InventoryPage />)
    // Multiple elements may show loading text simultaneously (table + status bar)
    const loadingEls = screen.queryAllByText(/讀取庫存資料中/i)
    expect(loadingEls.length).toBeGreaterThan(0)
  })
})
