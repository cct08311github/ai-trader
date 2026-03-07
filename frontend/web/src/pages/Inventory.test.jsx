import React from 'react'
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import InventoryPage from './Inventory'

describe('InventoryPage', () => {
  it('renders inventory dashboard title', async () => {
    render(<InventoryPage />)
    expect(await screen.findByText(/庫存總覽/i)).toBeInTheDocument()
  })

  it('shows loading state initially', async () => {
    render(<InventoryPage />)
    // Wait for the loading indicators to appear and potentially resolve
    const loadingEls = await screen.findAllByText(/讀取庫存資料中/i)
    expect(loadingEls.length).toBeGreaterThan(0)
  })
})
