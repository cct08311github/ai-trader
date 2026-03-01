// Inventory API for fetching inventory data
import { formatCurrency } from './format'

const DEFAULT_API_BASE = ''

const API_BASE = (import.meta?.env?.VITE_API_BASE || DEFAULT_API_BASE).replace(/\/$/, '')

// Mock inventory data for development
export const mockInventoryData = [
  {
    id: 1,
    code: 'AAPL',
    name: 'Apple Inc.',
    quantity: 150,
    unitCost: 175.50,
    currentValue: 26325.00,
    status: '正常'
  },
  {
    id: 2,
    code: 'TSLA',
    name: 'Tesla Inc.',
    quantity: 80,
    unitCost: 210.75,
    currentValue: 16860.00,
    status: '正常'
  },
  {
    id: 3,
    code: 'MSFT',
    name: 'Microsoft Corp.',
    quantity: 200,
    unitCost: 415.20,
    currentValue: 83040.00,
    status: '正常'
  },
  {
    id: 4,
    code: 'NVDA',
    name: 'NVIDIA Corp.',
    quantity: 50,
    unitCost: 950.80,
    currentValue: 47540.00,
    status: '低庫存'
  },
  {
    id: 5,
    code: 'GOOGL',
    name: 'Alphabet Inc.',
    quantity: 120,
    unitCost: 152.30,
    currentValue: 18276.00,
    status: '正常'
  },
  {
    id: 6,
    code: 'AMZN',
    name: 'Amazon.com Inc.',
    quantity: 90,
    unitCost: 178.90,
    currentValue: 16101.00,
    status: '正常'
  },
  {
    id: 7,
    code: 'META',
    name: 'Meta Platforms Inc.',
    quantity: 0,
    unitCost: 485.25,
    currentValue: 0,
    status: '缺貨'
  },
  {
    id: 8,
    code: 'TSM',
    name: 'Taiwan Semiconductor',
    quantity: 300,
    unitCost: 142.80,
    currentValue: 42840.00,
    status: '正常'
  },
  {
    id: 9,
    code: 'JPM',
    name: 'JPMorgan Chase & Co.',
    quantity: 25,
    unitCost: 195.40,
    currentValue: 4885.00,
    status: '低庫存'
  },
  {
    id: 10,
    code: 'V',
    name: 'Visa Inc.',
    quantity: 180,
    unitCost: 275.60,
    currentValue: 49608.00,
    status: '正常'
  }
]

// Fetch inventory data from API
export async function fetchInventoryData() {
  try {
    // Try to fetch from the backend API
    const response = await fetch(`${API_BASE}/api/inventory`, {
      headers: {
        'Accept': 'application/json',
        'Content-Type': 'application/json'
      }
    })

    if (!response.ok) {
      throw new Error(`API responded with status ${response.status}`)
    }

    const data = await response.json()

    // Validate and format the data
    return Array.isArray(data) ? data.map(item => ({
      id: item.id || Math.random(),
      code: item.code || item.symbol || 'N/A',
      name: item.name || item.description || 'Unknown',
      quantity: Number(item.quantity) || 0,
      unitCost: Number(item.unitCost) || 0,
      currentValue: Number(item.currentValue) || (Number(item.quantity) || 0) * (Number(item.unitCost) || 0),
      status: item.status || (Number(item.quantity) === 0 ? '缺貨' :
        (Number(item.quantity) < 10 ? '低庫存' : '正常'))
    })) : mockInventoryData

  } catch (error) {
    console.warn('Failed to fetch inventory data from API:', error.message)
    // Return empty array - do NOT fallback to mock. Real data only.
    return []
  }
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
