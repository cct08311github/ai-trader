export function formatCurrency(n, { currency = 'USD', maximumFractionDigits = 2 } = {}) {
  const value = Number(n)
  if (!Number.isFinite(value)) return '-'
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency,
    maximumFractionDigits
  }).format(value)
}

export function formatNumber(n, { maximumFractionDigits = 2 } = {}) {
  const value = Number(n)
  if (!Number.isFinite(value)) return '-'
  return new Intl.NumberFormat(undefined, { maximumFractionDigits }).format(value)
}

export function formatPercent(n, { maximumFractionDigits = 2 } = {}) {
  const value = Number(n)
  if (!Number.isFinite(value)) return '-'
  return new Intl.NumberFormat(undefined, {
    style: 'percent',
    maximumFractionDigits
  }).format(value)
}
