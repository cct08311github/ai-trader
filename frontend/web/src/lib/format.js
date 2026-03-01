// Shared number formatter — always use en-US grouping so commas appear consistently
// regardless of the user's browser locale setting.
const _groupFmt = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const _groupFmt2 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2, minimumFractionDigits: 2 })

/**
 * formatCurrency(580000)           → "TWD 580,000"
 * formatCurrency(-1234.5, {dp: 2}) → "TWD -1,234.50"
 */
export function formatCurrency(n, { currency = 'TWD', maximumFractionDigits = 0 } = {}) {
  const value = Number(n)
  if (!Number.isFinite(value)) return '-'
  const fmt = new Intl.NumberFormat('en-US', {
    maximumFractionDigits,
    minimumFractionDigits: 0,
    useGrouping: true,
  })
  return `${currency} ${fmt.format(value)}`
}

/**
 * formatNumber(1234567.89) → "1,234,567.89"
 */
export function formatNumber(n, { maximumFractionDigits = 2 } = {}) {
  const value = Number(n)
  if (!Number.isFinite(value)) return '-'
  return new Intl.NumberFormat('en-US', { maximumFractionDigits, useGrouping: true }).format(value)
}

/**
 * formatPercent(0.1234) → "12.34%"
 */
export function formatPercent(n, { maximumFractionDigits = 2 } = {}) {
  const value = Number(n)
  if (!Number.isFinite(value)) return '-'
  return `${new Intl.NumberFormat('en-US', { maximumFractionDigits, useGrouping: false }).format(value * 100)}%`
}

/**
 * formatComma(580000) → "580,000"  (no currency prefix, just grouping)
 */
export function formatComma(n, { maximumFractionDigits = 0 } = {}) {
  const value = Number(n)
  if (!Number.isFinite(value)) return '-'
  return new Intl.NumberFormat('en-US', { maximumFractionDigits, useGrouping: true }).format(value)
}
