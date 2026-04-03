import React, { useState, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useQuery } from '@tanstack/react-query'
import { DataCard } from '../components/ui/DataCard'
import { authFetch, getApiBase } from '../lib/auth'

// ── Constants ────────────────────────────────────────────────────────────────

const TABS = [
  { key: 'geopolitical', label: '地緣政治' },
  { key: 'market',       label: '金融市場' },
  { key: 'investment',   label: '投資中心' },
]

const TYPE_BADGE_COLORS = {
  geopolitical: 'rgb(var(--accent-danger, 220 38 38))',
  market:       'rgb(var(--accent-warn, 202 138 4))',
  investment:   'rgb(var(--accent, 34 197 94))',
}

const SENTIMENT_COLORS = {
  bullish:  '#16a34a',
  bearish:  '#dc2626',
  neutral:  '#71717a',
}

// ── API helpers ───────────────────────────────────────────────────────────────

async function fetchReportList(type, page = 1, perPage = 20) {
  const url = `${getApiBase()}/api/research-reports/list?type=${type}&page=${page}&per_page=${perPage}`
  const res = await authFetch(url)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

async function fetchReportDetail(id) {
  const res = await authFetch(`${getApiBase()}/api/research-reports/${id}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

async function triggerGenerate(type) {
  const res = await authFetch(`${getApiBase()}/api/research-reports/generate?type=${type}`, { method: 'POST' })
  if (!res.ok && res.status !== 202) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

// ── Sub-components ────────────────────────────────────────────────────────────

function TypeBadge({ reportType }) {
  const key = Object.keys(TYPE_BADGE_COLORS).find(k => reportType?.includes(k))
  const color = key ? TYPE_BADGE_COLORS[key] : 'rgb(var(--accent))'
  return (
    <span
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: '0.65rem',
        color,
        border: `1px solid ${color}`,
        borderRadius: '2px',
        padding: '1px 4px',
        letterSpacing: '0.05em',
        whiteSpace: 'nowrap',
      }}
    >
      {reportType || 'report'}
    </span>
  )
}

function SentimentBadge({ sentiment }) {
  if (!sentiment) return null
  const color = SENTIMENT_COLORS[sentiment] || SENTIMENT_COLORS.neutral
  return (
    <span
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: '0.65rem',
        color,
        letterSpacing: '0.05em',
      }}
    >
      {sentiment}
    </span>
  )
}

function Toast({ message, onClose }) {
  if (!message) return null
  return (
    <div
      style={{
        position: 'fixed',
        bottom: '1.5rem',
        right: '1.5rem',
        zIndex: 9999,
        background: 'rgb(var(--card))',
        border: '1px solid rgb(var(--accent))',
        borderLeft: '3px solid rgb(var(--accent))',
        padding: '0.6rem 1rem',
        borderRadius: '2px',
        fontFamily: 'var(--font-ui)',
        fontSize: '0.8rem',
        color: 'rgb(var(--text))',
        boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
        display: 'flex',
        alignItems: 'center',
        gap: '0.5rem',
      }}
    >
      <span style={{ flex: 1 }}>{message}</span>
      <button
        onClick={onClose}
        style={{
          background: 'none',
          border: 'none',
          color: 'rgb(var(--muted))',
          cursor: 'pointer',
          fontSize: '1rem',
          padding: 0,
          lineHeight: 1,
        }}
      >
        ×
      </button>
    </div>
  )
}

function MarkdownBody({ body }) {
  return (
    <div
      className="prose prose-invert max-w-none"
      style={{
        fontFamily: 'var(--font-ui)',
        fontSize: '0.85rem',
        color: 'rgb(var(--text))',
        lineHeight: 1.7,
      }}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => (
            <h1 style={{ fontSize: '1.1rem', fontWeight: 700, marginBottom: '0.5rem', color: 'rgb(var(--accent))' }}>
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 style={{ fontSize: '0.95rem', fontWeight: 600, marginBottom: '0.4rem', marginTop: '1rem', color: 'rgb(var(--text))' }}>
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.3rem', marginTop: '0.8rem', color: 'rgb(var(--muted))' }}>
              {children}
            </h3>
          ),
          p: ({ children }) => (
            <p style={{ marginBottom: '0.6rem', color: 'rgb(var(--text))' }}>{children}</p>
          ),
          strong: ({ children }) => (
            <strong style={{ color: 'rgb(var(--accent))', fontWeight: 600 }}>{children}</strong>
          ),
          ul: ({ children }) => (
            <ul style={{ paddingLeft: '1.2rem', marginBottom: '0.6rem', listStyleType: 'disc' }}>{children}</ul>
          ),
          ol: ({ children }) => (
            <ol style={{ paddingLeft: '1.2rem', marginBottom: '0.6rem', listStyleType: 'decimal' }}>{children}</ol>
          ),
          li: ({ children }) => (
            <li style={{ marginBottom: '0.2rem', color: 'rgb(var(--text))' }}>{children}</li>
          ),
          code: ({ inline, children }) =>
            inline ? (
              <code
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.78rem',
                  background: 'rgba(var(--border),0.4)',
                  padding: '1px 4px',
                  borderRadius: '2px',
                  color: 'rgb(var(--accent))',
                }}
              >
                {children}
              </code>
            ) : (
              <pre
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.78rem',
                  background: 'rgba(0,0,0,0.3)',
                  border: '1px solid rgb(var(--border))',
                  borderRadius: '2px',
                  padding: '0.6rem',
                  overflowX: 'auto',
                  marginBottom: '0.6rem',
                }}
              >
                <code>{children}</code>
              </pre>
            ),
          blockquote: ({ children }) => (
            <blockquote
              style={{
                borderLeft: '3px solid rgb(var(--accent))',
                paddingLeft: '0.8rem',
                margin: '0.5rem 0',
                color: 'rgb(var(--muted))',
                fontStyle: 'italic',
              }}
            >
              {children}
            </blockquote>
          ),
          table: ({ children }) => (
            <div style={{ overflowX: 'auto', marginBottom: '0.6rem' }}>
              <table
                style={{
                  width: '100%',
                  borderCollapse: 'collapse',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.78rem',
                }}
              >
                {children}
              </table>
            </div>
          ),
          th: ({ children }) => (
            <th
              style={{
                border: '1px solid rgb(var(--border))',
                padding: '4px 8px',
                background: 'rgba(var(--border),0.3)',
                color: 'rgb(var(--muted))',
                textAlign: 'left',
              }}
            >
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td
              style={{
                border: '1px solid rgb(var(--border))',
                padding: '4px 8px',
                color: 'rgb(var(--text))',
              }}
            >
              {children}
            </td>
          ),
          hr: () => (
            <hr style={{ border: 'none', borderTop: '1px solid rgb(var(--border))', margin: '0.8rem 0' }} />
          ),
          a: ({ href, children }) => {
            const safe = href?.startsWith('http') ? href : '#'
            return (
              <a href={safe} target="_blank" rel="noopener noreferrer" style={{ color: 'rgb(var(--accent))', textDecoration: 'underline' }}>
                {children}
              </a>
            )
          },
        }}
      >
        {body}
      </ReactMarkdown>
    </div>
  )
}

// ── PDF Export ────────────────────────────────────────────────────────────────

/**
 * exportReportPdf — dynamically imports html2canvas + jspdf and renders the
 * provided DOM element across multiple pages.
 *
 * Dynamic import is ONLY triggered on click, never at module load.
 */
async function exportReportPdf(element, filename = 'report.pdf') {
  // Dynamic import — bundler will code-split these heavy libs
  const [{ default: html2canvas }, { default: jsPDF }] = await Promise.all([
    import('html2canvas'),
    import('jspdf'),
  ])

  const canvas = await html2canvas(element, {
    scale: 2,
    useCORS: true,
    backgroundColor: '#0f1117',
    logging: false,
  })

  const imgData   = canvas.toDataURL('image/png')
  const imgWidth  = canvas.width
  const imgHeight = canvas.height

  const pdf       = new jsPDF({ orientation: 'portrait', unit: 'px', format: 'a4' })
  const pageWidth = pdf.internal.pageSize.getWidth()
  const pageHeight= pdf.internal.pageSize.getHeight()

  // Scale image to page width
  const scaledWidth  = pageWidth
  const scaledHeight = (imgHeight * pageWidth) / imgWidth

  let yOffset = 0

  // Multi-page: split by page height in a while loop
  while (yOffset < scaledHeight) {
    if (yOffset > 0) pdf.addPage()
    pdf.addImage(
      imgData,
      'PNG',
      0,
      -yOffset,
      scaledWidth,
      scaledHeight,
    )
    yOffset += pageHeight
  }

  pdf.save(filename)
}

function ExportPdfButton({ report, contentRef }) {
  const [exporting, setExporting] = React.useState(false)

  const handleExport = async (e) => {
    e.stopPropagation()   // don't toggle card expand/collapse
    if (exporting || !contentRef?.current) return
    setExporting(true)
    try {
      const filename = `report-${report.report_date || report.id}-${report.report_type || 'ai'}.pdf`
      await exportReportPdf(contentRef.current, filename)
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error('[PDF export]', err)
    } finally {
      setExporting(false)
    }
  }

  return (
    <button
      onClick={handleExport}
      disabled={exporting}
      title="匯出 PDF"
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: '0.65rem',
        letterSpacing: '0.05em',
        padding: '2px 7px',
        background: 'transparent',
        border: '1px solid rgb(var(--border))',
        borderRadius: '2px',
        color: exporting ? 'rgb(var(--muted))' : 'rgb(var(--text))',
        cursor: exporting ? 'not-allowed' : 'pointer',
        whiteSpace: 'nowrap',
        transition: 'border-color 0.15s ease, color 0.15s ease',
        flexShrink: 0,
      }}
      onMouseEnter={e => { if (!exporting) e.currentTarget.style.borderColor = 'rgb(var(--accent))' }}
      onMouseLeave={e => { e.currentTarget.style.borderColor = 'rgb(var(--border))' }}
    >
      {exporting ? '產生中…' : '↓ PDF'}
    </button>
  )
}

function ReportCard({ report, isExpanded, onToggle }) {
  const cardRef = React.useRef(null)

  const { data: detail, isLoading: detailLoading } = useQuery({
    queryKey: ['report-detail', report.id],
    queryFn: () => fetchReportDetail(report.id),
    enabled: isExpanded,
    staleTime: 5 * 60 * 1000,
  })

  const dateStr = report.report_date || report.created_at?.slice(0, 10) || '—'
  const confidence = report.confidence != null
    ? `${Math.round(report.confidence * 100)}%`
    : null

  return (
    <div
      ref={cardRef}
      style={{
        background: 'rgb(var(--card))',
        border: '1px solid rgb(var(--border))',
        borderLeft: `2px solid ${isExpanded ? 'rgb(var(--accent))' : 'rgb(var(--border))'}`,
        borderRadius: '2px',
        overflow: 'hidden',
        transition: 'border-left-color 0.15s ease',
      }}
    >
      {/* Card header — always visible */}
      <button
        onClick={onToggle}
        style={{
          width: '100%',
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          padding: '0.75rem 1rem',
          textAlign: 'left',
          display: 'flex',
          flexDirection: 'column',
          gap: '0.35rem',
        }}
      >
        {/* Top row: title + date + PDF export */}
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.5rem', justifyContent: 'space-between' }}>
          <span
            style={{
              fontFamily: 'var(--font-ui)',
              fontSize: '0.875rem',
              fontWeight: 600,
              color: 'rgb(var(--text))',
              flex: 1,
              lineHeight: 1.4,
            }}
          >
            {report.title}
          </span>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', flexShrink: 0 }}>
            <ExportPdfButton report={report} contentRef={cardRef} />
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '0.72rem',
                color: 'rgb(var(--muted))',
                whiteSpace: 'nowrap',
                paddingTop: '2px',
              }}
            >
              {dateStr}
            </span>
          </div>
        </div>

        {/* Badge row */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
          <TypeBadge reportType={report.report_type} />
          {report.sentiment && <SentimentBadge sentiment={report.sentiment} />}
          {confidence && (
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '0.65rem',
                color: 'rgb(var(--muted))',
                letterSpacing: '0.05em',
              }}
            >
              信心 {confidence}
            </span>
          )}
          <span
            style={{
              marginLeft: 'auto',
              fontFamily: 'var(--font-mono)',
              fontSize: '0.7rem',
              color: 'rgb(var(--muted))',
            }}
          >
            {isExpanded ? '▲' : '▼'}
          </span>
        </div>

        {/* Preview (collapsed only) */}
        {!isExpanded && report.preview && (
          <p
            style={{
              fontFamily: 'var(--font-ui)',
              fontSize: '0.78rem',
              color: 'rgb(var(--muted))',
              lineHeight: 1.5,
              margin: 0,
            }}
          >
            {report.preview}
            {report.preview.length >= 100 ? '…' : ''}
          </p>
        )}
      </button>

      {/* Expanded content */}
      {isExpanded && (
        <div
          style={{
            borderTop: '1px solid rgb(var(--border))',
            padding: '1rem',
          }}
        >
          {detailLoading ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '1rem 0' }}>
              <div
                style={{
                  width: '16px',
                  height: '16px',
                  border: '2px solid rgb(var(--border))',
                  borderTopColor: 'rgb(var(--accent))',
                  borderRadius: '50%',
                  animation: 'spin 0.8s linear infinite',
                }}
              />
              <span style={{ fontFamily: 'var(--font-ui)', fontSize: '0.8rem', color: 'rgb(var(--muted))' }}>
                載入中…
              </span>
            </div>
          ) : detail?.data?.body ? (
            <MarkdownBody body={detail.data.body} />
          ) : detail?.data?.summary ? (
            <p style={{ fontFamily: 'var(--font-ui)', fontSize: '0.85rem', color: 'rgb(var(--text))' }}>
              {detail.data.summary}
            </p>
          ) : (
            <p style={{ fontFamily: 'var(--font-ui)', fontSize: '0.8rem', color: 'rgb(var(--muted))' }}>
              無內容
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function ReportList({ activeTab }) {
  const [expandedId, setExpandedId] = useState(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['research-reports', activeTab],
    queryFn: () => fetchReportList(activeTab),
    staleTime: 2 * 60 * 1000,
    refetchOnWindowFocus: false,
  })

  const handleToggle = useCallback((id) => {
    setExpandedId(prev => (prev === id ? null : id))
  }, [])

  if (isLoading) {
    return <DataCard loading />
  }

  if (error) {
    return <DataCard error={error.message || '載入失敗'} />
  }

  const reports = data?.data || []

  if (reports.length === 0) {
    return (
      <DataCard empty={`尚無${TABS.find(t => t.key === activeTab)?.label || ''}報告`} />
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
      {reports.map(report => (
        <ReportCard
          key={report.id}
          report={report}
          isExpanded={expandedId === report.id}
          onToggle={() => handleToggle(report.id)}
        />
      ))}
      {data?.meta?.total > reports.length && (
        <p
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '0.72rem',
            color: 'rgb(var(--muted))',
            textAlign: 'center',
            padding: '0.5rem',
          }}
        >
          共 {data.meta.total} 筆，顯示前 {reports.length} 筆
        </p>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Reports() {
  const [activeTab, setActiveTab] = useState('geopolitical')
  const [toast, setToast] = useState(null)
  const [generating, setGenerating] = useState(false)

  const handleGenerate = useCallback(async () => {
    if (generating) return
    setGenerating(true)
    try {
      await triggerGenerate(activeTab)
      setToast(`已排入${TABS.find(t => t.key === activeTab)?.label}報告生成任務`)
    } catch (err) {
      setToast(`生成失敗：${err.message}`)
    } finally {
      setGenerating(false)
      setTimeout(() => setToast(null), 4000)
    }
  }, [activeTab, generating])

  return (
    <div style={{ padding: '1rem', maxWidth: '100%' }}>
      {/* Page header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '1rem',
          flexWrap: 'wrap',
          gap: '0.5rem',
        }}
      >
        <h1
          style={{
            fontFamily: 'var(--font-ui)',
            fontSize: '1.1rem',
            fontWeight: 600,
            color: 'rgb(var(--text))',
            margin: 0,
          }}
        >
          研究報告
        </h1>

        <button
          onClick={handleGenerate}
          disabled={generating}
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '0.75rem',
            letterSpacing: '0.05em',
            padding: '0.35rem 0.75rem',
            background: generating ? 'rgba(var(--border),0.4)' : 'transparent',
            border: '1px solid rgb(var(--accent))',
            borderRadius: '2px',
            color: generating ? 'rgb(var(--muted))' : 'rgb(var(--accent))',
            cursor: generating ? 'not-allowed' : 'pointer',
            transition: 'all 0.15s ease',
          }}
        >
          {generating ? '排程中…' : '+ 生成報告'}
        </button>
      </div>

      {/* Tabs */}
      <div
        style={{
          display: 'flex',
          gap: '0.25rem',
          marginBottom: '1rem',
          borderBottom: '1px solid rgb(var(--border))',
          paddingBottom: '0',
        }}
      >
        {TABS.map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            style={{
              fontFamily: 'var(--font-ui)',
              fontSize: '0.82rem',
              padding: '0.4rem 0.85rem',
              background: 'none',
              border: 'none',
              borderBottom: activeTab === tab.key
                ? '2px solid rgb(var(--accent))'
                : '2px solid transparent',
              color: activeTab === tab.key
                ? 'rgb(var(--accent))'
                : 'rgb(var(--muted))',
              cursor: 'pointer',
              fontWeight: activeTab === tab.key ? 600 : 400,
              transition: 'all 0.15s ease',
              marginBottom: '-1px',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Report list */}
      <ReportList activeTab={activeTab} />

      {/* Toast notification */}
      <Toast message={toast} onClose={() => setToast(null)} />

      {/* Inline spinner keyframe */}
      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  )
}
