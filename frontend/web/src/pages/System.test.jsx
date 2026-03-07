import React from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { ThemeProvider } from '../lib/theme'
import { ToastProvider } from '../components/ToastProvider'
import SystemPage from './System'

globalThis.__APP_VERSION__ = 'test'

const resolveCluster = vi.fn(async () => ({ resolved_count: 1 }))
const refreshClusters = vi.fn(async () => ({}))
const refreshRemediation = vi.fn(async () => ({}))
const refreshQuarantineStatus = vi.fn(async () => ({}))
const refreshQuarantinePlan = vi.fn(async () => ({}))
const applySuggestedQuarantine = vi.fn(async () => ({ applied_count: 2 }))
const clearAllQuarantine = vi.fn(async () => ({ cleared_count: 1 }))
const clearQuarantineSymbols = vi.fn(async () => ({ cleared_count: 1 }))

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
    refresh: refreshQuarantineStatus,
  }),
  useQuarantinePlan: () => ({
    data: { report_id: 'r-1', eligible_symbols: ['2330', '2317'], safe_to_apply: true },
    error: null,
    refresh: refreshQuarantinePlan,
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
        sample_detail: { current_ip: '8.8.8.8', allowlist: ['192.168.1.0/24'] },
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
  useQuarantineActions: () => ({
    loading: { apply: false, clear: false },
    lastAction: null,
    error: null,
    applySuggestedQuarantine,
    clearAllQuarantine,
    clearQuarantineSymbols,
  }),
}))

function renderPage() {
  return renderPageAt('/system')
}

function renderPageAt(entry) {
  return render(
    <ThemeProvider defaultTheme="dark">
      <ToastProvider>
        <MemoryRouter initialEntries={[entry]}>
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
    window.confirm = vi.fn(() => true)
  })

  it('renders operator panels and remediation data', () => {
    renderPage()

    expect(screen.getByText('Operator Snapshot')).toBeInTheDocument()
    expect(screen.getByText('Quarantine / Reconciliation')).toBeInTheDocument()
    expect(screen.getByText('Open Incident Clusters')).toBeInTheDocument()
    expect(screen.getByText('Remediation History')).toBeInTheDocument()
    expect(screen.getAllByText('2330').length).toBeGreaterThan(0)
    expect(screen.getByText(/network_security \/ SEC_NETWORK_IP_DENIED/)).toBeInTheDocument()
    expect(screen.getByText(/8.8.8.8/)).toBeInTheDocument()
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

  it('triggers quarantine apply action from the operator panel', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getByRole('button', { name: '套用建議隔離' }))

    expect(applySuggestedQuarantine).toHaveBeenCalled()
  })

  it('triggers single-symbol quarantine clear from the operator panel', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getByRole('button', { name: '清除此檔' }))

    expect(clearQuarantineSymbols).toHaveBeenCalledWith(['2330'])
  })

  it('updates operator filter inputs on the page', async () => {
    renderPage()

    const sourceInput = screen.getByPlaceholderText('network_security')
    const targetRefInput = screen.getByPlaceholderText('2330 / network_security')

    fireEvent.change(sourceInput, { target: { value: 'broker_reconciliation' } })
    fireEvent.change(targetRefInput, { target: { value: '2330' } })

    expect(sourceInput).toHaveValue('broker_reconciliation')
    expect(targetRefInput).toHaveValue('2330')
  })

  it('hydrates operator filters from query params', () => {
    renderPageAt('/system?incident_source=network_security&incident_code=SEC_NETWORK_IP_DENIED&remediation_target_ref=2330')

    expect(screen.getByPlaceholderText('network_security')).toHaveValue('network_security')
    expect(screen.getByPlaceholderText('SEC_NETWORK_IP_DENIED')).toHaveValue('SEC_NETWORK_IP_DENIED')
    expect(screen.getByPlaceholderText('2330 / network_security')).toHaveValue('2330')
  })

  it('applies incident preset shortcuts', () => {
    renderPage()

    fireEvent.click(screen.getByRole('button', { name: 'Network preset' }))

    expect(screen.getByPlaceholderText('network_security')).toHaveValue('network_security')
    expect(screen.getByPlaceholderText('SEC_NETWORK_IP_DENIED')).toHaveValue('SEC_NETWORK_IP_DENIED')
  })

  it('resets incident filters', () => {
    renderPageAt('/system?incident_source=network_security&incident_code=SEC_NETWORK_IP_DENIED&incident_severity=critical')

    fireEvent.click(screen.getAllByRole('button', { name: '清空' })[0])

    expect(screen.getByPlaceholderText('network_security')).toHaveValue('')
    expect(screen.getByPlaceholderText('SEC_NETWORK_IP_DENIED')).toHaveValue('')
  })

  it('applies remediation preset shortcuts', () => {
    renderPage()

    fireEvent.click(screen.getByRole('button', { name: 'Incident preset' }))

    expect(screen.getAllByRole('combobox')[1]).toHaveValue('incident_resolve')
    expect(screen.getByPlaceholderText('2330 / network_security')).toHaveValue('network_security')
  })

  it('resets remediation filters', () => {
    renderPageAt('/system?remediation_action_type=incident_resolve&remediation_target_ref=network_security')

    fireEvent.click(screen.getAllByRole('button', { name: '清空' })[1])

    expect(screen.getAllByRole('combobox')[1]).toHaveValue('')
    expect(screen.getByPlaceholderText('2330 / network_security')).toHaveValue('')
  })
})
