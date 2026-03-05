/**
 * symbolNames.js — 全域股票代號→名稱對照表
 *
 * 用法：
 *   import { useSymbolNames, formatSymbol } from '../lib/symbolNames'
 *
 *   const names = useSymbolNames()         // React hook，自動快取
 *   const label = formatSymbol('3008', names)  // "3008 大立光"
 */
import { useEffect, useState } from 'react'
import { authFetch, getApiBase } from './auth'

let _cache = null   // module-level cache; refreshed per page load

export function useSymbolNames() {
  const [names, setNames] = useState(_cache || {})

  useEffect(() => {
    if (_cache) return
    authFetch(`${getApiBase()}/api/portfolio/symbol-names`)
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (d?.names) {
          _cache = d.names
          setNames(d.names)
        }
      })
      .catch(() => {})
  }, [])

  return names
}

/**
 * Returns "3008 大立光" if name is known, or just "3008" otherwise.
 * @param {string} symbol
 * @param {Record<string,string>} names   — from useSymbolNames()
 */
export function formatSymbol(symbol, names) {
  if (!symbol) return symbol
  const name = names?.[symbol]
  return name && name !== symbol ? `${symbol} ${name}` : symbol
}
