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
    expect(screen.getByText(/Loading…/i)).toBeDefined()
  })
})
