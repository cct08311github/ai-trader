import React, { useEffect, useRef, useState } from 'react'
import { X, AlertCircle, CheckCircle2, Loader2 } from 'lucide-react'
import { authFetch, getApiBase, getToken } from '../../lib/auth'
import ChatMessage from './ChatMessage'
import ChatInput from './ChatInput'

const MAX_HISTORY = 50

export default function ChatPanel({ onClose }) {
  const [messages, setMessages] = useState([])
  const [streaming, setStreaming] = useState(false)
  const [modelName, setModelName] = useState('')
  const [error, setError] = useState(null)
  const [proposal, setProposal] = useState(null)  // {action, symbol, qty, price}
  const [proposalStatus, setProposalStatus] = useState(null) // 'ok' | 'error'
  const bottomRef = useRef(null)

  // Load history on mount
  useEffect(() => {
    authFetch(`${getApiBase()}/api/chat/history`)
      .then(r => r.json())
      .then(data => {
        const hist = (data.history || []).slice(-MAX_HISTORY)
        const msgs = []
        for (const h of hist) {
          // Each trace has a single Q&A pair encoded in prompt/response
          const userMsg = _extractUserMsg(h.prompt)
          if (userMsg) msgs.push({ role: 'user', content: userMsg })
          if (h.response) msgs.push({ role: 'assistant', content: h.response })
        }
        if (msgs.length > 0) setMessages(msgs)
      })
      .catch(() => { /* non-critical */ })
  }, [])

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSend = async (userText) => {
    setError(null)
    setProposal(null)
    setProposalStatus(null)

    // Add user message
    const newMessages = [...messages, { role: 'user', content: userText }]
    setMessages(newMessages)

    // Add placeholder for AI response
    const aiIndex = newMessages.length
    setMessages(prev => [...prev, { role: 'assistant', content: '', streaming: true }])
    setStreaming(true)

    // Build history for context (last 6 messages before this one)
    const historyForApi = newMessages.slice(-6).map(m => ({
      role: m.role,
      content: m.content,
    }))

    try {
      const token = getToken()
      const resp = await fetch(`${getApiBase()}/api/chat/message`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ message: userText, history: historyForApi }),
      })

      if (!resp.ok) {
        throw new Error(`API error ${resp.status}`)
      }

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let aiText = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        // Parse SSE lines
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''  // keep incomplete last line

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const parsed = JSON.parse(line.slice(6))
            if (parsed.type === 'chunk') {
              aiText += parsed.text
              setMessages(prev => {
                const updated = [...prev]
                if (updated[aiIndex]) {
                  updated[aiIndex] = { role: 'assistant', content: aiText, streaming: true }
                }
                return updated
              })
            } else if (parsed.type === 'done') {
              setModelName(parsed.model || '')
              if (parsed.proposal) setProposal(parsed.proposal)
              setMessages(prev => {
                const updated = [...prev]
                if (updated[aiIndex]) {
                  updated[aiIndex] = { role: 'assistant', content: aiText, streaming: false }
                }
                return updated
              })
            } else if (parsed.type === 'error') {
              setError(parsed.text)
            }
          } catch { /* skip malformed */ }
        }
      }
    } catch (e) {
      setError(`連線失敗：${e.message}`)
      setMessages(prev => {
        const updated = [...prev]
        if (updated[aiIndex]) {
          updated[aiIndex] = { role: 'assistant', content: '（回應失敗）', streaming: false }
        }
        return updated
      })
    } finally {
      setStreaming(false)
    }
  }

  const handleCreateProposal = async () => {
    if (!proposal) return
    const lastAiMsg = [...messages].reverse().find(m => m.role === 'assistant')?.content || ''
    const lastUserMsg = [...messages].reverse().find(m => m.role === 'user')?.content || ''
    try {
      const res = await authFetch(`${getApiBase()}/api/chat/create-proposal`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ai_response: lastAiMsg, user_message: lastUserMsg }),
      })
      const data = await res.json()
      if (res.ok) {
        setProposalStatus('ok')
        setProposal(null)
      } else {
        setProposalStatus('error')
      }
    } catch {
      setProposalStatus('error')
    }
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[rgb(var(--border))] px-4 py-3">
        <div>
          <div className="text-sm font-semibold">AI 策略助手</div>
          {modelName && (
            <div className="text-xs text-[rgb(var(--muted))]">
              {modelName}
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg p-1.5 text-[rgb(var(--muted))] transition hover:bg-[rgb(var(--surface))/0.5] hover:text-[rgb(var(--text))]"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 space-y-3 overflow-y-auto p-4 scrollbar-thin">
        {messages.length === 0 && !streaming && (
          <div className="py-8 text-center text-xs text-[rgb(var(--muted))]">
            <div className="mb-2 text-2xl">🤖</div>
            <div>詢問持倉風險、策略分析或特定股票</div>
            <div className="mt-1 text-[rgb(var(--muted))]/60">
              例：「目前持倉集中度如何？」、「2330 還能加碼嗎？」
            </div>
          </div>
        )}
        {messages.map((msg, i) => (
          <ChatMessage
            key={i}
            role={msg.role}
            content={msg.content}
            isStreaming={msg.streaming}
          />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Proposal chip */}
      {proposal && (
        <div className="mx-4 mb-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3">
          <div className="mb-2 text-xs font-medium text-emerald-400">
            偵測到交易建議
          </div>
          <div className="mb-2 text-sm text-[rgb(var(--text))]">
            {proposal.action === 'buy' ? '買入' : '賣出'} {proposal.symbol} {proposal.qty} 股 @{proposal.price}
          </div>
          <button
            type="button"
            onClick={handleCreateProposal}
            className="w-full rounded-lg bg-emerald-600/80 px-3 py-1.5 text-xs font-medium text-white
                       transition hover:bg-emerald-500 active:scale-[0.98]"
          >
            生成策略提案（需人工審核後才下單）
          </button>
        </div>
      )}

      {/* Proposal status */}
      {proposalStatus === 'ok' && (
        <div className="mx-4 mb-2 flex items-center gap-2 rounded-xl bg-emerald-500/10 px-3 py-2 text-xs text-emerald-400">
          <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
          提案已建立，請至 Strategy 頁面審核。
        </div>
      )}
      {proposalStatus === 'error' && (
        <div className="mx-4 mb-2 flex items-center gap-2 rounded-xl bg-rose-500/10 px-3 py-2 text-xs text-rose-400">
          <AlertCircle className="h-3.5 w-3.5 shrink-0" />
          建立提案失敗，請重試。
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="mx-4 mb-2 rounded-xl bg-rose-500/10 px-3 py-2 text-xs text-rose-400">
          {error}
        </div>
      )}

      {/* Streaming indicator */}
      {streaming && (
        <div className="mx-4 mb-1 flex items-center gap-1.5 text-xs text-[rgb(var(--muted))]">
          <Loader2 className="h-3 w-3 animate-spin" />
          AI 思考中…
        </div>
      )}

      {/* Input */}
      <ChatInput onSend={handleSend} disabled={streaming} />
    </div>
  )
}

// Extract user message from the stored prompt (format: "[system]\n...\n\n[user]\n{msg}")
function _extractUserMsg(prompt) {
  if (!prompt) return null
  const marker = '[user]\n'
  const idx = prompt.lastIndexOf(marker)
  if (idx === -1) return null
  return prompt.slice(idx + marker.length).trim()
}
