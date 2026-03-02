import React, { useRef, useState } from 'react'
import { Send } from 'lucide-react'

export default function ChatInput({ onSend, disabled }) {
  const [value, setValue] = useState('')
  const textareaRef = useRef(null)

  const handleSend = () => {
    const msg = value.trim()
    if (!msg || disabled) return
    onSend(msg)
    setValue('')
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleChange = (e) => {
    setValue(e.target.value)
    // Auto-grow textarea
    const ta = textareaRef.current
    if (ta) {
      ta.style.height = 'auto'
      ta.style.height = `${Math.min(ta.scrollHeight, 120)}px`
    }
  }

  return (
    <div className="flex items-end gap-2 border-t border-[rgb(var(--border))] p-3">
      <textarea
        ref={textareaRef}
        rows={1}
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        placeholder="詢問策略、持倉、風險… (Enter 送出, Shift+Enter 換行)"
        className="flex-1 resize-none rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.4]
                   px-3 py-2 text-sm text-[rgb(var(--text))] placeholder-[rgb(var(--muted))]
                   outline-none focus:border-emerald-500/50 focus:ring-1 focus:ring-emerald-500/25
                   disabled:opacity-50 max-h-[120px] leading-relaxed"
      />
      <button
        type="button"
        onClick={handleSend}
        disabled={disabled || !value.trim()}
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl
                   bg-emerald-600/80 text-white transition hover:bg-emerald-500
                   disabled:opacity-40 disabled:cursor-not-allowed active:scale-95"
      >
        <Send className="h-4 w-4" />
      </button>
    </div>
  )
}
