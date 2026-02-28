import { describe, expect, it } from 'vitest'
import { tradesToCsv, tradesToExcelXml } from './trades'

describe('trades export', () => {
  it('csv has header and rows', () => {
    const csv = tradesToCsv([
      { id: 't1', timestamp: '2026-02-28T00:00:00Z', symbol: '2330', action: 'buy', quantity: 1, price: 100, pnl: 0, fee: 1, tax: 0 }
    ])

    expect(csv).toContain('timestamp,symbol,action,quantity,price,amount,pnl,fee,tax,id')
    expect(csv).toContain('2026-02-28T00:00:00Z,2330,buy,1,100,100,0,1,0,t1')
  })

  it('excel xml contains worksheet and values', () => {
    const xml = tradesToExcelXml([
      { id: 't1', timestamp: '2026-02-28T00:00:00Z', symbol: '2330', action: 'buy', quantity: 1, price: 100, amount: 100, pnl: 0, fee: 1, tax: 0 }
    ])

    expect(xml).toContain('<Worksheet')
    expect(xml).toContain('Trades')
    expect(xml).toContain('2330')
    expect(xml).toContain('t1')
  })
})
