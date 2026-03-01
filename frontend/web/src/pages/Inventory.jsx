import React, { useEffect, useState } from 'react'
import KpiCard from '../components/KpiCard'
import { fetchInventoryData, mockInventoryData } from '../lib/inventoryApi'
import { formatCurrency, formatNumber, formatPercent } from '../lib/format'

function InventoryTable({ data, loading }) {
  if (loading) {
    return (
      <div className="rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.3] p-8 text-center text-[rgb(var(--muted))]">
        讀取庫存資料中...
      </div>
    )
  }

  if (!data || data.length === 0) {
    return (
      <div className="py-16 text-center text-sm text-[rgb(var(--muted))]">
        No inventory data available.
      </div>
    )
  }

  const totalValue = data.reduce((sum, item) => sum + (item.currentValue || 0), 0)

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-left text-sm">
        <thead className="text-xs uppercase tracking-wider text-[rgb(var(--muted))]">
          <tr>
            <th className="px-4 py-3">商品代碼</th>
            <th className="px-4 py-3">商品名稱</th>
            <th className="px-4 py-3">庫存數量</th>
            <th className="px-4 py-3">單位成本</th>
            <th className="px-4 py-3">當前價值</th>
            <th className="px-4 py-3">庫存占比</th>
            <th className="px-4 py-3">狀態</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[rgb(var(--border))]">
          {data.map((item) => {
            const weight = totalValue > 0 ? (item.currentValue || 0) / totalValue : 0
            const statusColor = item.status === '正常' ? 'text-emerald-600 dark:text-emerald-300' :
              item.status === '低庫存' ? 'text-amber-600 dark:text-amber-300' :
                item.status === '缺貨' ? 'text-rose-600 dark:text-rose-300' : 'text-[rgb(var(--muted))]'

            return (
              <tr key={item.id} className="hover:bg-[rgb(var(--surface))/0.35]">
                <td className="px-4 py-3 font-medium text-[rgb(var(--text))]">{item.code}</td>
                <td className="px-4 py-3 text-[rgb(var(--text))]">{item.name}</td>
                <td className="px-4 py-3 text-[rgb(var(--text))]">{formatNumber(item.quantity, { maximumFractionDigits: 2 })}</td>
                <td className="px-4 py-3 text-[rgb(var(--text))]">{formatCurrency(item.unitCost)}</td>
                <td className="px-4 py-3 text-[rgb(var(--text))]">{formatCurrency(item.currentValue)}</td>
                <td className="px-4 py-3 text-[rgb(var(--text))]">{formatPercent(weight)}</td>
                <td className={`px-4 py-3 ${statusColor}`}>{item.status}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function InventoryChart({ data }) {
  if (!data || data.length === 0) {
    return (
      <div className="py-16 text-center text-sm text-[rgb(var(--muted))]">
        No data for chart visualization.
      </div>
    )
  }

  // Simple bar chart visualization
  const maxValue = Math.max(...data.map(item => item.currentValue || 0))

  return (
    <div className="space-y-2">
      {data.map((item) => {
        const percentage = maxValue > 0 ? (item.currentValue / maxValue) * 100 : 0
        return (
          <div key={item.id} className="flex items-center gap-3">
            <div className="w-24 truncate text-sm">{item.name}</div>
            <div className="flex-1">
              <div className="h-6 rounded bg-[rgb(var(--surface))/0.5] overflow-hidden">
                <div
                  className="h-full bg-emerald-500/30 transition-all duration-300"
                  style={{ width: `${percentage}%` }}
                />
              </div>
            </div>
            <div className="w-20 text-right text-sm">{formatCurrency(item.currentValue)}</div>
          </div>
        )
      })}
    </div>
  )
}

export default function InventoryPage() {
  const [inventoryData, setInventoryData] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [useMock, setUseMock] = useState(false)

  const loadData = async (useMockData = false) => {
    setLoading(true)
    setError(null)

    try {
      if (useMockData) {
        setInventoryData(mockInventoryData)
        setUseMock(true)
      } else {
        const data = await fetchInventoryData()
        setInventoryData(data)
        setUseMock(false)
      }
    } catch (err) {
      setError(err.message)
      setInventoryData(mockInventoryData)
      setUseMock(true)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData(false)
  }, [])

  // Calculate KPIs
  const totalItems = inventoryData.length
  const totalValue = inventoryData.reduce((sum, item) => sum + (item.currentValue || 0), 0)
  const lowStockCount = inventoryData.filter(item => item.status === '低庫存').length
  const outOfStockCount = inventoryData.filter(item => item.status === '缺貨').length

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="text-sm font-semibold">庫存總覽 (Inventory Dashboard)</div>
          <div className="mt-1 text-xs text-[rgb(var(--muted))]">
            Data source:{' '}
            <span
              className={
                !useMock
                  ? 'rounded-md bg-emerald-500/10 px-2 py-0.5 text-emerald-600 dark:text-emerald-300 ring-1 ring-emerald-500/20'
                  : 'rounded-md bg-[rgb(var(--surface))/0.45] px-2 py-0.5 text-[rgb(var(--text))] ring-1 ring-[rgb(var(--border))]'
              }
            >
              {useMock ? 'MOCK' : 'API'}
            </span>
            {error ? <span className="ml-2 text-rose-600 dark:text-rose-300">(fallback: {error})</span> : null}
          </div>

          <label className="mt-3 inline-flex items-center gap-2 text-xs text-[rgb(var(--muted))]">
            <input
              type="checkbox"
              className="h-4 w-4"
              checked={useMock}
              onChange={(e) => {
                const v = e.target.checked
                loadData(v)
              }}
            />
            Use mock data (toggle for testing)
          </label>
        </div>

        <button
          type="button"
          onClick={() => loadData(useMock)}
          disabled={loading}
          className="w-full sm:w-auto rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.35] px-4 py-2 text-sm text-[rgb(var(--text))] shadow-panel transition hover:bg-[rgb(var(--surface))/0.5] disabled:opacity-50"
        >
          {loading ? '讀取中…' : '重新整理'}
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="總庫存項目"
          value={totalItems}
          subtext="Total inventory items"
        />
        <KpiCard
          title="總庫存價值"
          value={formatCurrency(totalValue)}
          subtext="Total inventory value"
        />
        <KpiCard
          title="低庫存項目"
          value={lowStockCount}
          subtext="Items with low stock"
          tone={lowStockCount > 0 ? 'warning' : 'good'}
        />
        <KpiCard
          title="缺貨項目"
          value={outOfStockCount}
          subtext="Out of stock items"
          tone={outOfStockCount > 0 ? 'bad' : 'good'}
        />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section className="rounded-2xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.25] shadow-panel">
          <div className="flex items-center justify-between border-b border-[rgb(var(--border))] px-4 py-3">
            <div className="text-sm font-semibold">庫存價值分布</div>
            <div className="text-xs text-[rgb(var(--muted))]">{inventoryData.length} items</div>
          </div>
          <div className="p-4">
            <InventoryChart data={inventoryData} />
          </div>
        </section>

        <section className="rounded-2xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.25] shadow-panel">
          <div className="flex items-center justify-between border-b border-[rgb(var(--border))] px-4 py-3">
            <div className="text-sm font-semibold">庫存狀態概覽</div>
            <div className="text-xs text-[rgb(var(--muted))]">
              {inventoryData.filter(item => item.status === '正常').length} normal
            </div>
          </div>
          <div className="p-4">
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-sm">正常庫存</span>
                <span className="text-sm font-medium text-emerald-600 dark:text-emerald-300">
                  {inventoryData.filter(item => item.status === '正常').length}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm">低庫存</span>
                <span className="text-sm font-medium text-amber-600 dark:text-amber-300">
                  {lowStockCount}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm">缺貨</span>
                <span className="text-sm font-medium text-rose-600 dark:text-rose-300">
                  {outOfStockCount}
                </span>
              </div>
            </div>
          </div>
        </section>
      </div>

      <section className="rounded-2xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.2] shadow-panel">
        <div className="flex items-center justify-between border-b border-[rgb(var(--border))] px-4 py-3">
          <div className="text-sm font-semibold">詳細庫存列表</div>
          <div className="text-xs text-[rgb(var(--muted))]">
            Total value: {formatCurrency(totalValue)}
          </div>
        </div>
        <div className="p-4">
          <InventoryTable data={inventoryData} loading={loading} />
        </div>
        <div className="border-t border-[rgb(var(--border))] px-4 py-3 text-xs text-[rgb(var(--muted))]">
          Note: This inventory dashboard shows real-time stock levels and values. Data updates automatically.
        </div>
      </section>

      <div className="text-right text-xs text-[rgb(var(--muted))]">
        {loading ? '讀取庫存資料中...' : `庫存資料來源：${useMock ? '模擬資料' : 'API'}`}
      </div>
    </div>
  )
}
