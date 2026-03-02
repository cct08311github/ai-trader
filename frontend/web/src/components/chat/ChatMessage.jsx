import React from 'react'
import { Bot, User } from 'lucide-react'

export default function ChatMessage({ role, content, isStreaming }) {
  const isAI = role === 'assistant'

  return (
    <div className={`flex gap-2 ${isAI ? 'items-start' : 'items-start justify-end'}`}>
      {isAI && (
        <div className="mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-emerald-500/20 ring-1 ring-emerald-500/30">
          <Bot className="h-3.5 w-3.5 text-emerald-400" />
        </div>
      )}

      <div
        className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm leading-relaxed ${
          isAI
            ? 'rounded-tl-sm bg-[rgb(var(--surface))/0.5] text-[rgb(var(--text))] ring-1 ring-[rgb(var(--border))]'
            : 'rounded-tr-sm bg-emerald-600/20 text-emerald-100 ring-1 ring-emerald-500/30'
        }`}
      >
        <span className="whitespace-pre-wrap break-words">{content}</span>
        {isStreaming && (
          <span className="ml-1 inline-block h-3 w-0.5 animate-pulse bg-emerald-400" />
        )}
      </div>

      {!isAI && (
        <div className="mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[rgb(var(--surface))/0.5] ring-1 ring-[rgb(var(--border))]">
          <User className="h-3.5 w-3.5 text-[rgb(var(--muted))]" />
        </div>
      )}
    </div>
  )
}
