import React from 'react'
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { axe } from 'jest-axe'
import { ThemeProvider } from '../lib/theme'
import { ToastProvider } from '../components/ToastProvider'
import PortfolioPage from './Portfolio'

function renderPage() {
  return render(
    <ThemeProvider defaultTheme="dark">
      <ToastProvider>
        <MemoryRouter initialEntries={['/portfolio']}>
          <PortfolioPage />
        </MemoryRouter>
      </ToastProvider>
    </ThemeProvider>
  )
}

describe('PortfolioPage', () => {
  it('renders KPI cards and positions table headers', () => {
    renderPage()

    expect(screen.getByText(/庫存總覽/i)).toBeInTheDocument()
    expect(screen.getByText('總資產')).toBeInTheDocument()
    expect(screen.getByText('日損益')).toBeInTheDocument()
    expect(screen.getByText('累計損益')).toBeInTheDocument()
    expect(screen.getByText('夏普比率')).toBeInTheDocument()

    expect(screen.getByText('持倉列表')).toBeInTheDocument()
    expect(screen.getByText('代碼')).toBeInTheDocument()
    expect(screen.getByText('成本')).toBeInTheDocument()
    expect(screen.getByText('現價')).toBeInTheDocument()
    expect(screen.getByText('未實現損益')).toBeInTheDocument()
    expect(screen.getByText('持倉比例')).toBeInTheDocument()
  })

  it('has no obvious a11y violations (basic)', async () => {
    const { container } = renderPage()
    const results = await axe(container)
    expect(results).toHaveNoViolations()
  })
})
