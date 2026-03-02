// Inventory API for fetching inventory data
import { formatCurrency } from './format'
import { authFetch, getApiBase } from './auth'

// Fetch inventory data from DB (positions table via /api/inventory)
export async function fetchInventoryData() {
  const response = await authFetch(`${getApiBase()}/api/inventory`)
  if (!response.ok) throw new Error(`API ${response.status}`)
  const data = await response.json()
  if (!Array.isArray(data)) throw new Error('Invalid response format')
  return data.map(item => ({
    id: item.id || item.code,
    code: item.code || item.symbol || 'N/A',
    name: item.name || item.code || 'Unknown',
    quantity: Number(item.quantity) || 0,
    unitCost: Number(item.unitCost) || 0,
    currentValue: Number(item.currentValue) || 0,
    status: item.status || (Number(item.quantity) === 0 ? '缺貨' : '正常'),
    chip_health_score: item.chip_health_score ?? null,
    sector: item.sector || null,
  }))
}

// Calculate inventory statistics
export function calculateInventoryStats(data) {
  if (!Array.isArray(data) || data.length === 0) {
    return {
      totalItems: 0,
      totalValue: 0,
      lowStockCount: 0,
      outOfStockCount: 0,
      normalStockCount: 0
    }
  }

  return {
    totalItems: data.length,
    totalValue: data.reduce((sum, item) => sum + (item.currentValue || 0), 0),
    lowStockCount: data.filter(item => item.status === '低庫存').length,
    outOfStockCount: data.filter(item => item.status === '缺貨').length,
    normalStockCount: data.filter(item => item.status === '正常').length
  }
}

// Format inventory item for display
export function formatInventoryItem(item) {
  return {
    ...item,
    formattedQuantity: item.quantity.toLocaleString(),
    formattedUnitCost: formatCurrency(item.unitCost),
    formattedCurrentValue: formatCurrency(item.currentValue)
  }
}
