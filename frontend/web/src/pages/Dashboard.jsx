import React, { useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import { DataCard } from '../components/ui/DataCard'
import { MetricBadge } from '../components/ui/MetricBadge'
import { AlertBadge } from '../components/ui/AlertBadge'
import { SentimentIndicator } from '../components/ui/SentimentIndicator'
import { authFetch, getApiBase } from '../lib/auth'

// ── Fetchers ──────────────────────────────────────────────────────────────────

async function fetchIndices() {
  const res = await authFetch(`${getApiBase()}/api/indices/latest`)
  if (!res.ok) throw new Error(`指數載入失敗 (${res.status})`)
  return res.json()
}

async function fetchPortfolioSummary() {
  const res = await authFetch(`${getApiBase()}/api/portfolio/summary`)
  if (!res.ok) throw new Error(`投組摘要載入失敗 (${res.status})`)
  return res.json()
}

async function fetchLatestAnalysis() {
  const res = await authFetch(`${getApiBase()}/api/analysis/latest`)
  if (!res.ok) throw new Error(`分析快照載入失敗 (${res.status})`)
  return res.json()
}

// ── Mock action queue (structure ready for real data) ────────────────────────

const MOCK_ACTION_QUEUE = [
  {
    id: 'aq-1',
    type: 'stop_loss',
    symbol: '華邦電',
    ticker: '4532',
    message: '華邦電距停損線 3%，建議執行停損',
    level: 'red',
    primaryLabel: '執行停損',
    secondaryLabel: '忽略',
  },
  {
    id: 'aq-2',
    type: 'ai_suggest',
    symbol: '廣達',
    ticker: '2382',
    message: 'AI 建議加碼廣達：籌碼集中度上升，本週外資淨買超',
    level: 'yellow',
    primaryLabel: '查看分析',
    secondaryLabel: '稍後',
  },
]

// ── Helpers ──────────────────────────────────────────────────────────────────

function pnlTrend(value) {
  if (value == null) return 'flat'
  return value > 0 ? 'up' : value < 0 ? 'down' : 'flat'
}

function formatPct(val) {
  if (val == null) return null
  return `${val > 0 ? '+' : ''}${Number(val).toFixed(2)}%`
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SectionHeading({ children }) {
  return (
    <h2
      className="text-xs font-semibold uppercase tracking-widest text-th-muted mb-2"
      style={{ fontFamily: 'var(--font-mono)' }}
    >
      {children}
    </h2>
  )
}

/** KPI row item — wraps MetricBadge in a themed tile */
function KpiTile({ label, value, trend, format, subtext, accentColor }) {
  return (
    <div
      className="flex flex-col gap-1 px-4 py-3 rounded-sm border border-th-border border-l-2 bg-th-card shadow-panel"
      style={{ borderLeftColor: accentColor || 'rgb(var(--accent))' }}
    >
      <span
        className="text-[10px] tracking-widest uppercase text-th-muted"
        style={{ fontFamily: 'var(--font-mono)' }}
      >
        {label}
      </span>
      <MetricBadge value={value} trend={trend} format={format} />
      {subtext && (
        <span
          className="text-[10px] text-th-muted truncate mt-0.5"
          style={{ fontFamily: 'var(--font-ui)' }}
        >
          {subtext}
        </span>
      )}
    </div>
  )
}

/** Gainers / losers row */
function MoverRow({ symbol, name, changePct, isGainer }) {
  const color = isGainer ? 'rgb(var(--up))' : 'rgb(var(--down))'
  const arrow = isGainer ? '▲' : '▼'
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-th-border last:border-0">
      <div className="flex flex-col min-w-0">
        <span
          className="text-xs font-medium truncate"
          style={{ color: 'rgb(var(--text))', fontFamily: 'var(--font-ui)' }}
        >
          {name || symbol}
        </span>
        <span
          className="text-[10px] text-th-muted"
          style={{ fontFamily: 'var(--font-mono)' }}
        >
          {symbol}
        </span>
      </div>
      <span
        className="text-sm tabular-nums flex-shrink-0 ml-3"
        style={{ color, fontFamily: 'var(--font-data)' }}
      >
        {arrow} {Math.abs(changePct).toFixed(2)}%
      </span>
    </div>
  )
}

/** Unrealized P&L bar */
function PnlBar({ totalPnl, totalCost }) {
  const pct = totalCost > 0 ? (totalPnl / totalCost) * 100 : 0
  const clampedPct = Math.min(Math.abs(pct), 100)
  const positive = pct >= 0
  const barColor = positive ? 'rgb(var(--up))' : 'rgb(var(--down))'

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span
          className="text-[10px] uppercase tracking-widest text-th-muted"
          style={{ fontFamily: 'var(--font-mono)' }}
        >
          未實現損益
        </span>
        <span
          className="text-sm tabular-nums font-semibold"
          style={{ color: barColor, fontFamily: 'var(--font-data)' }}
        >
          {positive ? '+' : ''}
          {new Intl.NumberFormat('zh-TW', {
            style: 'currency',
            currency: 'TWD',
            minimumFractionDigits: 0,
          }).format(totalPnl)}
          <span className="text-xs ml-1">
            ({positive ? '+' : ''}{pct.toFixed(2)}%)
          </span>
        </span>
      </div>
      <div className="w-full h-1.5 rounded-full bg-th-border overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${clampedPct}%`, backgroundColor: barColor }}
        />
      </div>
    </div>
  )
}

/** Single action queue item with two buttons */
function ActionItem({ item, onPrimary, onSecondary, dismissed }) {
  if (dismissed) return null
  return (
    <div className="flex items-start gap-3 px-3 py-2.5 rounded-sm border border-th-border bg-th-card">
      <div className="flex-1 min-w-0">
        <span
          className="text-xs text-th-muted block mb-0.5"
          style={{ fontFamily: 'var(--font-mono)' }}
        >
          [{item.ticker}] {item.symbol}
        </span>
        <span
          className="text-xs"
          style={{ color: 'rgb(var(--text))', fontFamily: 'var(--font-ui)' }}
        >
          {item.message}
        </span>
      </div>
      <div className="flex gap-2 flex-shrink-0 mt-0.5">
        <button
          onClick={onPrimary}
          className="text-xs px-2 py-0.5 rounded-sm border transition-opacity hover:opacity-80"
          style={{
            color: item.level === 'red' ? 'rgb(var(--danger))' : 'rgb(var(--accent))',
            borderColor: item.level === 'red' ? 'rgb(var(--danger))' : 'rgb(var(--accent))',
            fontFamily: 'var(--font-mono)',
          }}
        >
          {item.primaryLabel}
        </button>
        <button
          onClick={onSecondary}
          className="text-xs px-2 py-0.5 rounded-sm border border-th-border text-th-muted transition-opacity hover:opacity-80"
          style={{ fontFamily: 'var(--font-mono)' }}
        >
          {item.secondaryLabel}
        </button>
      </div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const [dismissedActions, setDismissedActions] = useState(new Set())

  const dismissAction = useCallback((id) => {
    setDismissedActions((prev) => new Set([...prev, id]))
  }, [])

  // React Query fetches
  const indicesQ = useQuery({
    queryKey: ['indices-latest'],
    queryFn: fetchIndices,
    staleTime: 60_000,
    retry: 1,
  })

  const portfolioQ = useQuery({
    queryKey: ['portfolio-summary'],
    queryFn: fetchPortfolioSummary,
    staleTime: 60_000,
    retry: 1,
  })

  const analysisQ = useQuery({
    queryKey: ['analysis-latest'],
    queryFn: fetchLatestAnalysis,
    staleTime: 5 * 60_000,
    retry: 1,
  })

  // Derived values from API data (with safe fallbacks)
  const indices = indicesQ.data || {}
  const portfolio = portfolioQ.data || {}
  const analysis = analysisQ.data || null

  const totalValue = portfolio.total_value ?? null
  const dailyChangePct = portfolio.daily_change_pct ?? null
  const unrealizedPnl = portfolio.unrealized_pnl ?? null
  const totalCost = portfolio.total_cost ?? 1

  const vixLevel = indices.vix ?? null
  const vixTrend = indices.vix_trend ?? null
  const taixChange = indices.taiex_change_pct ?? null

  // Derive alert-level counts from portfolio risk data
  const riskAlerts = portfolio.alerts || []
  const redAlerts = riskAlerts.filter((a) => a.level === 'red')
  const yellowAlerts = riskAlerts.filter((a) => a.level === 'yellow')

  // Derive gainers / losers from portfolio positions
  const positions = portfolio.positions || []
  const sorted = [...positions].sort(
    (a, b) => (b.change_pct ?? 0) - (a.change_pct ?? 0)
  )
  const gainers = sorted.filter((p) => (p.change_pct ?? 0) > 0).slice(0, 3)
  const losers = sorted
    .filter((p) => (p.change_pct ?? 0) < 0)
    .reverse()
    .slice(0, 3)

  // Analysis sentiment
  const sentiment = analysis?.strategy?.sentiment ?? 'neutral'
  const analysisSummary = analysis?.strategy?.summary ?? null
  const analysisDate = analysis?.trade_date ?? null

  // Active alerts count KPI (API alerts + mock action queue)
  const activeAlertsCount =
    redAlerts.length + yellowAlerts.length + MOCK_ACTION_QUEUE.length

  // VIX sentiment mapping
  const vixSentiment =
    vixLevel == null ? 'neutral' : vixLevel > 25 ? 'bearish' : vixLevel < 15 ? 'bullish' : 'neutral'

  return (
    <div className="space-y-5">
      {/* ── KPI Row ──────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KpiTile
          label="投組總值"
          value={totalValue}
          format="currency"
          trend={pnlTrend(dailyChangePct)}
          subtext={dailyChangePct != null ? `今日 ${formatPct(dailyChangePct)}` : '—'}
          accentColor="rgb(var(--accent))"
        />
        <KpiTile
          label="VIX 波動指數"
          value={vixLevel}
          format="number"
          trend={vixTrend === 'up' ? 'up' : vixTrend === 'down' ? 'down' : undefined}
          subtext={<SentimentIndicator sentiment={vixSentiment} />}
          accentColor={vixLevel != null && vixLevel > 25 ? 'rgb(var(--danger))' : 'rgb(var(--warn))'}
        />
        <KpiTile
          label="加權指數 (TAIEX)"
          value={taixChange != null ? formatPct(taixChange) : null}
          format="raw"
          trend={pnlTrend(taixChange)}
          subtext="今日漲跌幅"
          accentColor={
            taixChange == null
              ? 'rgb(var(--accent))'
              : taixChange >= 0
              ? 'rgb(var(--up))'
              : 'rgb(var(--down))'
          }
        />
        <KpiTile
          label="活躍警報"
          value={activeAlertsCount}
          format="number"
          trend={activeAlertsCount > 0 ? 'down' : 'flat'}
          subtext={`${redAlerts.length} 緊急 · ${yellowAlerts.length} 警告`}
          accentColor={
            redAlerts.length > 0 ? 'rgb(var(--danger))' : 'rgb(var(--warn))'
          }
        />
      </div>

      {/* ── Alert Section (Priority 1) ────────────────────────────────────── */}
      {(redAlerts.length > 0 || yellowAlerts.length > 0) && (
        <section>
          <SectionHeading>警報中心</SectionHeading>
          <div className="space-y-2">
            {redAlerts.map((a, i) => (
              <AlertBadge
                key={a.id || a.symbol || `red-${i}`}
                level="red"
                message={a.message}
                actionLabel={a.action_label}
                onAction={a.on_action}
              />
            ))}
            {yellowAlerts.map((a, i) => (
              <AlertBadge
                key={a.id || a.symbol || `yellow-${i}`}
                level="yellow"
                message={a.message}
                actionLabel={a.action_label}
                onAction={a.on_action}
              />
            ))}
          </div>
        </section>
      )}

      {/* ── Portfolio + Market — asymmetric grid (3:2) ────────────────────── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        {/* Portfolio Summary — 3/5 width on desktop */}
        <div className="lg:col-span-3 space-y-3">
          <SectionHeading>投組摘要</SectionHeading>

          {/* P&L summary bar */}
          <DataCard
            loading={portfolioQ.isLoading}
            error={portfolioQ.isError ? portfolioQ.error?.message : null}
            accentColor="rgb(var(--accent))"
          >
            {unrealizedPnl != null ? (
              <PnlBar totalPnl={unrealizedPnl} totalCost={totalCost} />
            ) : (
              <p className="text-xs text-th-muted" style={{ fontFamily: 'var(--font-ui)' }}>
                未實現損益資料尚未載入
              </p>
            )}
          </DataCard>

          {/* Gainers / Losers */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <DataCard
              title="今日漲幅前三"
              loading={portfolioQ.isLoading}
              error={portfolioQ.isError ? portfolioQ.error?.message : null}
              empty={gainers.length === 0 && !portfolioQ.isLoading ? '今日無上漲持倉' : false}
              accentColor="rgb(var(--up))"
            >
              <div className="divide-y divide-th-border">
                {gainers.map((p) => (
                  <MoverRow
                    key={p.symbol}
                    symbol={p.symbol}
                    name={p.name}
                    changePct={p.change_pct}
                    isGainer
                  />
                ))}
              </div>
            </DataCard>

            <DataCard
              title="今日跌幅前三"
              loading={portfolioQ.isLoading}
              error={portfolioQ.isError ? portfolioQ.error?.message : null}
              empty={losers.length === 0 && !portfolioQ.isLoading ? '今日無下跌持倉' : false}
              accentColor="rgb(var(--down))"
            >
              <div className="divide-y divide-th-border">
                {losers.map((p) => (
                  <MoverRow
                    key={p.symbol}
                    symbol={p.symbol}
                    name={p.name}
                    changePct={p.change_pct}
                    isGainer={false}
                  />
                ))}
              </div>
            </DataCard>
          </div>

          <div className="text-right">
            <Link
              to="/portfolio"
              className="text-xs text-th-muted hover:text-th-text transition-colors"
              style={{ fontFamily: 'var(--font-ui)' }}
            >
              查看完整持倉 →
            </Link>
          </div>
        </div>

        {/* Market Pulse — 2/5 width on desktop */}
        <div className="lg:col-span-2 space-y-3">
          <SectionHeading>市場脈動</SectionHeading>

          {/* Latest analysis snapshot */}
          <DataCard
            title="盤後分析摘要"
            loading={analysisQ.isLoading}
            error={analysisQ.isError ? analysisQ.error?.message : null}
            empty={!analysis && !analysisQ.isLoading ? '尚無分析資料' : false}
            accentColor="rgb(var(--accent))"
          >
            {analysis && (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <SentimentIndicator sentiment={sentiment} />
                  <span
                    className="text-[10px] text-th-muted"
                    style={{ fontFamily: 'var(--font-mono)' }}
                  >
                    {analysisDate}
                  </span>
                </div>
                {analysisSummary && (
                  <p
                    className="text-xs leading-relaxed text-th-text line-clamp-4 mt-1"
                    style={{ fontFamily: 'var(--font-ui)' }}
                  >
                    {analysisSummary}
                  </p>
                )}
                <div className="pt-1">
                  <Link
                    to="/analysis"
                    className="text-xs text-th-muted hover:text-th-text transition-colors"
                    style={{ fontFamily: 'var(--font-ui)' }}
                  >
                    完整報告 →
                  </Link>
                </div>
              </div>
            )}
          </DataCard>

          {/* Key indices snapshot */}
          <DataCard
            title="關鍵指數"
            loading={indicesQ.isLoading}
            error={indicesQ.isError ? indicesQ.error?.message : null}
            empty={!indicesQ.data && !indicesQ.isLoading ? '指數資料未載入' : false}
            accentColor="rgb(var(--warn))"
          >
            <div className="space-y-2.5">
              {[
                { key: 'taiex', label: 'TAIEX', val: indices.taiex, changePct: taixChange },
                { key: 'nasdaq', label: 'NASDAQ', val: indices.nasdaq, changePct: indices.nasdaq_change_pct },
                { key: 'sp500', label: 'S&P 500', val: indices.sp500, changePct: indices.sp500_change_pct },
                { key: 'sox', label: 'SOX', val: indices.sox, changePct: indices.sox_change_pct },
              ].map(({ key, label, val, changePct }) => (
                <div key={key} className="flex items-center justify-between">
                  <span
                    className="text-[10px] uppercase tracking-wider text-th-muted"
                    style={{ fontFamily: 'var(--font-mono)' }}
                  >
                    {label}
                  </span>
                  <div className="flex items-baseline gap-2">
                    {val != null ? (
                      <span
                        className="text-xs tabular-nums"
                        style={{ fontFamily: 'var(--font-data)', color: 'rgb(var(--text))' }}
                      >
                        {new Intl.NumberFormat('zh-TW').format(Math.round(val))}
                      </span>
                    ) : (
                      <span className="text-xs text-th-muted">—</span>
                    )}
                    {changePct != null && (
                      <span
                        className="text-[10px] tabular-nums"
                        style={{
                          fontFamily: 'var(--font-data)',
                          color: changePct >= 0 ? 'rgb(var(--up))' : 'rgb(var(--down))',
                        }}
                      >
                        {formatPct(changePct)}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </DataCard>
        </div>
      </div>

      {/* ── Action Queue ─────────────────────────────────────────────────────── */}
      <section>
        <SectionHeading>待辦行動</SectionHeading>
        <div className="space-y-2">
          {MOCK_ACTION_QUEUE.map((item) => (
            <ActionItem
              key={item.id}
              item={item}
              dismissed={dismissedActions.has(item.id)}
              onPrimary={() => {
                if (item.type === 'ai_suggest') {
                  window.location.href = '/analysis'
                }
                // stop_loss: real impl would send order via API
              }}
              onSecondary={() => dismissAction(item.id)}
            />
          ))}
          {MOCK_ACTION_QUEUE.every((i) => dismissedActions.has(i.id)) && (
            <p
              className="text-xs text-th-muted py-2 text-center"
              style={{ fontFamily: 'var(--font-ui)' }}
            >
              無待辦行動
            </p>
          )}
        </div>
      </section>

      {/* Accessibility live region */}
      <div className="sr-only" aria-live="polite">
        {indicesQ.isLoading || portfolioQ.isLoading ? '載入儀表板資料中…' : '資料已更新'}
      </div>
    </div>
  )
}
