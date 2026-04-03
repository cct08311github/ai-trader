import React from 'react'
import { DataCard } from '../components/ui/DataCard'

/**
 * Reports — placeholder for /reports
 */
export default function Reports() {
  return (
    <div className="space-y-4 p-4">
      <h1
        className="text-lg font-medium text-th-text mb-4"
        style={{ fontFamily: 'var(--font-ui)' }}
      >
        研究報告
      </h1>
      <DataCard title="AI 生成報告" empty="報告模組開發中" />
      <DataCard title="歷史報告" empty="即將上線" />
    </div>
  )
}
