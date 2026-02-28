const API_URL = 'http://localhost:8080/api/portfolio/trades'

export const mockTrades = [
  {
    id: 'mock-1',
    timestamp: '2026-02-28T09:01:02Z',
    symbol: '2330',
    action: 'buy',
    quantity: 1,
    price: 1000,
    fee: 1,
    tax: 0,
    pnl: 0,
    amount: 1000,
    status: 'filled'
  },
  {
    id: 'mock-2',
    timestamp: '2026-02-28T13:10:00Z',
    symbol: '2330',
    action: 'sell',
    quantity: 1,
    price: 1012,
    fee: 1,
    tax: 1,
    pnl: 10,
    amount: 1012,
    status: 'filled'
  }
]

export async function fetchTrades(
  {
    start,
    end,
    symbol,
    type,
    status,
    limit = 50,
    offset = 0,
    sortBy = 'time',
    sortDir = 'desc',
    signal
  } = {}
) {
  const url = new URL(API_URL)
  if (start) url.searchParams.set('start', start)
  if (end) url.searchParams.set('end', end)
  if (symbol) url.searchParams.set('symbol', symbol)
  if (type) url.searchParams.set('type', type)
  if (status) url.searchParams.set('status', status)
  url.searchParams.set('limit', String(limit))
  url.searchParams.set('offset', String(offset))
  url.searchParams.set('sort_by', sortBy)
  url.searchParams.set('sort_dir', sortDir)

  const res = await fetch(url.toString(), { signal })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const data = await res.json()

  if (!data || data.status !== 'ok' || !Array.isArray(data.items)) {
    throw new Error('Invalid API response')
  }

  return data
}

function escapeCsvCell(value) {
  const s = String(value ?? '')
  if (/[\n\r",]/.test(s)) return `"${s.replaceAll('"', '""')}"`
  return s
}

export function tradesToCsv(trades) {
  const rows = Array.isArray(trades) ? trades : []
  const header = ['timestamp', 'symbol', 'action', 'quantity', 'price', 'amount', 'pnl', 'fee', 'tax', 'id']
  const lines = [header.join(',')]

  for (const t of rows) {
    const line = [
      t.timestamp,
      t.symbol,
      t.action,
      t.quantity,
      t.price,
      t.amount ?? Number(t.quantity || 0) * Number(t.price || 0),
      t.pnl,
      t.fee,
      t.tax,
      t.id
    ]
      .map(escapeCsvCell)
      .join(',')
    lines.push(line)
  }

  return lines.join('\n') + '\n'
}

// Excel: simple SpreadsheetML 2003 XML (.xls) without external dependencies
export function tradesToExcelXml(trades, { sheetName = 'Trades' } = {}) {
  const rows = Array.isArray(trades) ? trades : []
  const cols = ['timestamp', 'symbol', 'action', 'quantity', 'price', 'amount', 'pnl', 'fee', 'tax', 'id']

  function escXml(s) {
    return String(s ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&apos;')
  }

  const headerRow = `<Row>${cols.map((c) => `<Cell><Data ss:Type="String">${escXml(c)}</Data></Cell>`).join('')}</Row>`
  const bodyRows = rows
    .map((t) => {
      const values = {
        timestamp: t.timestamp,
        symbol: t.symbol,
        action: t.action,
        quantity: t.quantity,
        price: t.price,
        amount: t.amount ?? Number(t.quantity || 0) * Number(t.price || 0),
        pnl: t.pnl,
        fee: t.fee,
        tax: t.tax,
        id: t.id
      }
      const cells = cols
        .map((k) => {
          const v = values[k]
          const isNum = typeof v === 'number' && Number.isFinite(v)
          const type = isNum ? 'Number' : 'String'
          return `<Cell><Data ss:Type="${type}">${escXml(v)}</Data></Cell>`
        })
        .join('')
      return `<Row>${cells}</Row>`
    })
    .join('')

  return `<?xml version="1.0"?>\n` +
    `<?mso-application progid="Excel.Sheet"?>\n` +
    `<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"\n` +
    ` xmlns:o="urn:schemas-microsoft-com:office:office"\n` +
    ` xmlns:x="urn:schemas-microsoft-com:office:excel"\n` +
    ` xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">\n` +
    `<Worksheet ss:Name="${escXml(sheetName)}"><Table>` +
    headerRow +
    bodyRows +
    `</Table></Worksheet></Workbook>`
}

export function downloadTextFile(text, filename, mime = 'text/plain;charset=utf-8') {
  const blob = new Blob([text], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
