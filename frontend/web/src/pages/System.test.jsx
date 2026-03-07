import React from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { ThemeProvider } from '../lib/theme'
import { ToastProvider } from '../components/ToastProvider'
import SystemPage from './System'

globalThis.__APP_VERSION__ = 'test'

const resolveCluster = vi.fn(async () => ({ resolved_count: 1 }))
const refreshClusters = vi.fn(async () => ({}))
const refreshRemediation = vi.fn(async () => ({}))

vi.mock('../components/ControlPanel', () => ({
  default: () => <div>ControlPanel Mock</div>,
}))

vi.mock('../components/LogTerminal', () => ({
  default: () => <div>LogTerminal Mock</div>,
}))

vi.mock('../lib/systemApi', () => ({
  useSystemHealth: () => ({
    data: {
      services: {
        fastapi: { status: 'online', latency_ms: 12 },
        sqlite: { status: 'online', latency_ms: 3 },
        shioaji: { status: 'simulation' },
        sentinel: { status: 'online', last_heartbeat: new Date().toISOString(), today_circuit_breaks: 0 },
      },
      resources: { cpu_percent: 10, memory_percent: 20, disk_used_gb: 1, disk_total_gb: 10 },
      db_health: { wal_size_bytes: 1024, write_latency_p99_ms: 15 },
    },
    error: null,
  }),
  useSystemQuota: () => ({
    data: { month: '2026-03', budget_twd: 1000, used_twd: 120, used_percent: 12, status: 'ok', daily_trend: [] },
  }),
  useSystemRisk: () => ({
    data: { today_realized_pnl: 1234, monthly_drawdown_pct: 0.02, monthly_drawdown_limit_pct: 0.15, drawdown_remaining_pct: 0.13, losing_streak_days: 0, risk_mode: 'normal' },
  }),
  useSystemEvents: () => ({
    data: { events: [] },
  }),
  useQuarantineStatus: () => ({
    data: { active_count: 1, items: [{ symbol: '2330', reason_code: 'BROKER_POSITION_MISSING', position: { quantity: 0 } }] },
  }),
  useQuarantinePlan: () => ({
    data: { report_id: 'r-1', eligible_symbols: ['2330', '2317'] },
    error: null,
  }),
  useOpenIncidentClusters: () => ({
    data: {
      count: 1,
      items: [{
        source: 'network_security',
        code: 'SEC_NETWORK_IP_DENIED',
        count: 2,
        latest_ts: '2026-03-07T00:00:00Z',
        fingerprint: 'network_security|SEC_NETWORK_IP_DENIED|x',
      }],
    },
    resolveCluster,
    resolvingFingerprint: '',
    refresh: refreshClusters,
  }),
  useRemediationHistory: () => ({
    data: {
      count: 1,
      items: [{
        action_id: 'a1',
        action_type: 'incident_resolve',
        target_ref: 'network_security|SEC_NETWORK_IP_DENIED|x',
        actor: 'operator',
        status: 'resolved',
        created_at: 1741305600000,
      }],
    },
    refresh: refreshRemediation,
  }),
}))

function renderPage() {
  return render(
    <ThemeProvider defaultTheme="dark">
      <ToastProvider>
        <MemoryRouter initialEntries={['/system']}>
          <SystemPage />
        </MemoryRouter>
      </ToastProvider>
    </ThemeProvider>
  )
}

describe('SystemPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.prompt = vi.fn(() => 'root cause remediated')
  })

  it('renders operator panels and remediation data', () => {
    renderPage()

    expect(screen.getByText('Operator Snapshot')).toBeInTheDocument()
    expect(screen.getByText('Quarantine / Reconciliation')).toBeInTheDocument()
    expect(screen.getByText('Open Incident Clusters')).toBeInTheDocument()
    expect(screen.getByText('Remediation History')).toBeInTheDocument()
    expect(screen.getAllByText('2330').length).toBeGreaterThan(0)
    expect(screen.getByText(/network_security \/ SEC_NETWORK_IP_DENIED/)).toBeInTheDocument()
  })

  it('triggers cluster resolution from the operator panel', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getByRole('button', { name: '標記已處理' }))

    expect(resolveCluster).toHaveBeenCalledWith({
      source: 'network_security',
      code: 'SEC_NETWORK_IP_DENIED',
      fingerprint: 'network_security|SEC_NETWORK_IP_DENIED|x',
      reason: 'root cause remediated',
    })
  })
})
