import React from 'react'
import { DataCard } from '../components/ui/DataCard'

/**
 * Geopolitical — placeholder for /geopolitical
 */
export default function Geopolitical() {
  return (
    <div className="space-y-4 p-4">
      <h1
        className="text-lg font-medium text-th-text mb-4"
        style={{ fontFamily: 'var(--font-ui)' }}
      >
        地緣政治分析
      </h1>
      <DataCard title="全球風險地圖" empty="地緣政治模組開發中" />
      <DataCard title="新聞情緒" empty="即將上線" />
    </div>
  )
}
