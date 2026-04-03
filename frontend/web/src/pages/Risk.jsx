import React from 'react'
import { DataCard } from '../components/ui/DataCard'
import { AlertBadge } from '../components/ui/AlertBadge'

/**
 * Risk — placeholder for /risk
 */
export default function Risk() {
  return (
    <div className="space-y-4 p-4">
      <h1
        className="text-lg font-medium text-th-text mb-4"
        style={{ fontFamily: 'var(--font-ui)' }}
      >
        風險管理
      </h1>
      <AlertBadge level="yellow" message="風險模組建置中，即將上線" />
      <DataCard title="曝險分析" empty="即將上線" />
    </div>
  )
}
