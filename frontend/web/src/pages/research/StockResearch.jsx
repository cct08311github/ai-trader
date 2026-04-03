import React from 'react'
import { DataCard } from '../../components/ui/DataCard'

/**
 * StockResearch — placeholder for /research/stock
 */
export default function StockResearch() {
  return (
    <div className="space-y-4">
      <h1
        className="text-lg font-medium text-th-text mb-4"
        style={{ fontFamily: 'var(--font-ui)' }}
      >
        個股分析
      </h1>
      <DataCard title="K 線圖" empty="請輸入股票代碼開始分析" />
      <DataCard title="財務指標" empty="即將上線" />
    </div>
  )
}
