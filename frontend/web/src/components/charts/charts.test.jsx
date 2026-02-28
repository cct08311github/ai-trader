import React from 'react'
import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import AllocationDonut from './AllocationDonut'
import PnlLineChart from './PnlLineChart'

describe('Charts', () => {
  it('renders allocation donut (svg exists)', () => {
    const { container } = render(
      <div style={{ width: 800, height: 300 }}>
        <AllocationDonut
          data={[
            { name: 'AAPL', value: 1000, weight: 0.5 },
            { name: 'TSLA', value: 1000, weight: 0.5 }
          ]}
        />
      </div>
    )
    expect(container.querySelector('svg')).toBeTruthy()
  })

  it('renders pnl line chart (svg exists)', () => {
    const { container } = render(
      <div style={{ width: 800, height: 300 }}>
        <PnlLineChart data={[{ date: '01-01', equity: 100 }, { date: '01-02', equity: 110 }]} />
      </div>
    )
    expect(container.querySelector('svg')).toBeTruthy()
  })
})
