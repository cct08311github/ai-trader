import React from 'react'
import { DataCard } from '../../components/ui/DataCard'
import { SentimentIndicator } from '../../components/ui/SentimentIndicator'

/**
 * ResearchDashboard — placeholder for /research index
 * Will be replaced with full AI research overview in Sprint 5
 */
export default function ResearchDashboard() {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between mb-2">
        <h1
          className="text-lg font-medium text-th-text"
          style={{ fontFamily: 'var(--font-ui)' }}
        >
          AI 投資研究中心
        </h1>
        <SentimentIndicator sentiment="neutral" />
      </div>

      <DataCard title="市場概況" accentColor="rgb(var(--info))" empty="研究模組建置中，敬請期待" />

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <DataCard title="熱門標的" empty="即將上線" />
        <DataCard title="AI 訊號" empty="即將上線" />
      </div>
    </div>
  )
}
