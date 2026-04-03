import React from 'react'
import { DataCard } from '../../components/ui/DataCard'

/**
 * Screener — placeholder for /research/screener
 */
export default function Screener() {
  return (
    <div className="space-y-4">
      <h1
        className="text-lg font-medium text-th-text mb-4"
        style={{ fontFamily: 'var(--font-ui)' }}
      >
        選股器
      </h1>
      <DataCard title="條件篩選" empty="選股功能開發中" />
    </div>
  )
}
