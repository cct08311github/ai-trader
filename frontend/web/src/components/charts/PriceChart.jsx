import React, { useEffect, useRef } from 'react'
import { createChart, CandlestickSeries, LineSeries } from 'lightweight-charts'

/**
 * Calculate Simple Moving Average
 * @param {Array} data - OHLCV array [{time, open, high, low, close}]
 * @param {number} period
 * @returns {Array} [{time, value}]
 */
function calcMA(data, period) {
  const result = []
  for (let i = period - 1; i < data.length; i++) {
    const slice = data.slice(i - period + 1, i + 1)
    const avg = slice.reduce((sum, d) => sum + d.close, 0) / period
    result.push({ time: data[i].time, value: parseFloat(avg.toFixed(2)) })
  }
  return result
}

/**
 * PriceChart — TradingView lightweight-charts candlestick chart
 * with MA5 / MA20 / MA60 overlay
 *
 * Props:
 *   data   — Array of { time: 'YYYY-MM-DD', open, high, low, close, volume }
 *   symbol — Ticker string shown in top-left label
 *   height — Number (default 320)
 */
export function PriceChart({ data = [], symbol = '', height = 320 }) {
  const containerRef = useRef(null)
  const chartRef = useRef(null)

  useEffect(() => {
    if (!containerRef.current) return

    // Resolve CSS variable colors from :root
    const style = getComputedStyle(document.documentElement)
    const resolve = (varName, fallback) => {
      const raw = style.getPropertyValue(varName).trim()
      return raw ? `rgb(${raw})` : fallback
    }

    const upColor   = resolve('--up',      '#10b981')
    const downColor = resolve('--down',    '#e11d48')
    const bgColor   = resolve('--card',    '#0d131e')
    const gridColor = resolve('--border',  '#334155')
    const textColor = resolve('--muted',   '#64748b')

    const chart = createChart(containerRef.current, {
      width:  containerRef.current.clientWidth,
      height,
      layout: {
        background: { color: bgColor },
        textColor,
        fontFamily: 'var(--font-data), "Fira Code", monospace',
        fontSize: 11,
      },
      grid: {
        vertLines:  { color: `${gridColor}55` },
        horzLines:  { color: `${gridColor}55` },
      },
      crosshair: {
        mode: 1,
      },
      rightPriceScale: {
        borderColor: gridColor,
      },
      timeScale: {
        borderColor: gridColor,
        timeVisible: true,
        secondsVisible: false,
      },
    })

    chartRef.current = chart

    // Candlestick series
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor,
      downColor,
      borderUpColor:   upColor,
      borderDownColor: downColor,
      wickUpColor:     upColor,
      wickDownColor:   downColor,
    })

    if (data.length > 0) {
      candleSeries.setData(data)

      // MA5 — short-term (info color)
      const ma5Color = resolve('--info', '#06b6d4')
      const ma5Series = chart.addSeries(LineSeries, {
        color:       ma5Color,
        lineWidth:   1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      })
      ma5Series.setData(calcMA(data, 5))

      // MA20 — medium-term (warn color)
      const ma20Color = resolve('--warn', '#fb923c')
      const ma20Series = chart.addSeries(LineSeries, {
        color:       ma20Color,
        lineWidth:   1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      })
      ma20Series.setData(calcMA(data, 20))

      // MA60 — long-term (gold color)
      const ma60Color = resolve('--gold', '#a18a5a')
      const ma60Series = chart.addSeries(LineSeries, {
        color:       ma60Color,
        lineWidth:   1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      })
      ma60Series.setData(calcMA(data, 60))

      chart.timeScale().fitContent()
    }

    // Responsive resize
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        chart.applyOptions({ width: entry.contentRect.width })
      }
    })
    ro.observe(containerRef.current)

    return () => {
      ro.disconnect()
      chart.remove()
      chartRef.current = null
    }
  }, [data, height])

  return (
    <div className="relative w-full rounded-sm overflow-hidden border border-th-border bg-th-card">
      {/* Symbol label overlay */}
      {symbol && (
        <div
          className="absolute top-2 left-3 z-10 text-xs text-th-accent pointer-events-none"
          style={{ fontFamily: 'var(--font-data)' }}
        >
          {symbol}
        </div>
      )}

      {/* MA legend */}
      <div
        className="absolute top-2 right-3 z-10 flex items-center gap-3 text-xs pointer-events-none"
        style={{ fontFamily: 'var(--font-data)', fontSize: '10px' }}
      >
        <span style={{ color: 'rgb(var(--info))' }}>MA5</span>
        <span style={{ color: 'rgb(var(--warn))' }}>MA20</span>
        <span style={{ color: 'rgb(var(--gold))' }}>MA60</span>
      </div>

      {data.length === 0 && (
        <div
          className="absolute inset-0 flex items-center justify-center z-10"
          style={{ height }}
        >
          <span className="text-xs text-th-muted" style={{ fontFamily: 'var(--font-ui)' }}>
            尚無 K 線資料
          </span>
        </div>
      )}

      <div ref={containerRef} style={{ width: '100%', height }} />
    </div>
  )
}

export default PriceChart
