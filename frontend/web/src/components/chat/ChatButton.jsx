import React, { useState } from 'react'
import { MessageSquare, X } from 'lucide-react'
import ChatPanel from './ChatPanel'

export default function ChatButton() {
  const [open, setOpen] = useState(false)

  return (
    <>
      {/* Floating toggle button — sits to the left of FloatingLogout */}
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        aria-label={open ? '關閉 AI 助手' : '開啟 AI 助手'}
        className="fixed bottom-6 right-20 z-50 flex h-12 w-12 items-center justify-center
                   rounded-full bg-emerald-600 shadow-lg shadow-emerald-900/40
                   ring-2 ring-emerald-500/30 transition-all hover:bg-emerald-500
                   hover:scale-105 active:scale-95"
      >
        {open
          ? <X className="h-5 w-5 text-white" />
          : <MessageSquare className="h-5 w-5 text-white" />
        }
      </button>

      {/* Compact floating chat window — no backdrop, no overlay */}
      {open && (
        <div
          className="fixed bottom-24 right-6 z-50 flex flex-col
                     w-[360px] h-[480px] max-h-[calc(100vh-120px)]
                     rounded-2xl border border-[rgb(var(--border))]
                     bg-[rgb(var(--bg))] shadow-2xl shadow-black/50"
          style={{ resize: 'none' }}
        >
          <ChatPanel onClose={() => setOpen(false)} />
        </div>
      )}
    </>
  )
}
