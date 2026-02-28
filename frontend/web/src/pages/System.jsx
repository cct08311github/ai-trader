import React from 'react'
import ControlPanel from '../components/ControlPanel'
import LogTerminal from '../components/LogTerminal'

export default function SystemPage() {
  return (
    <div className="space-y-6">
      <div>
        <div className="text-sm font-semibold">系統監控與控制</div>
        <div className="mt-1 text-xs text-slate-400">
          主開關、緊急停止、模擬/實際盤切換。風險控制是第一優先。
        </div>
      </div>

      <ControlPanel />

      <LogTerminal />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 系統健康狀態 */}
        <div className="lg:col-span-2 rounded-2xl border border-slate-800 bg-slate-900/20 p-6 shadow-panel">
          <div className="text-sm font-semibold">系統健康狀態</div>
          <div className="mt-4 space-y-4">
            <div className="flex items-center justify-between">
              <div className="text-sm text-slate-300">後端 API</div>
              <div className="flex items-center gap-2">
                <span className="inline-block h-2 w-2 rounded-full bg-emerald-400"></span>
                <span className="text-xs text-emerald-300">在線</span>
              </div>
            </div>
            <div className="flex items-center justify-between">
              <div className="text-sm text-slate-300">資料庫連線</div>
              <div className="flex items-center gap-2">
                <span className="inline-block h-2 w-2 rounded-full bg-emerald-400"></span>
                <span className="text-xs text-emerald-300">正常</span>
              </div>
            </div>
            <div className="flex items-center justify-between">
              <div className="text-sm text-slate-300">Shioaji 連線</div>
              <div className="flex items-center gap-2">
                <span className="inline-block h-2 w-2 rounded-full bg-amber-400"></span>
                <span className="text-xs text-amber-300">模擬模式</span>
              </div>
            </div>
            <div className="flex items-center justify-between">
              <div className="text-sm text-slate-300">決策管線</div>
              <div className="flex items-center gap-2">
                <span className="inline-block h-2 w-2 rounded-full bg-emerald-400"></span>
                <span className="text-xs text-emerald-300">就緒</span>
              </div>
            </div>
          </div>
        </div>

        {/* 快速操作 */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/20 p-6 shadow-panel">
          <div className="text-sm font-semibold">快速操作</div>
          <div className="mt-4 space-y-3">
            <button className="w-full rounded-lg bg-slate-800 py-2.5 text-sm font-medium text-slate-300 hover:bg-slate-700 transition-all">
              查看日誌
            </button>
            <button className="w-full rounded-lg bg-slate-800 py-2.5 text-sm font-medium text-slate-300 hover:bg-slate-700 transition-all">
              重新整理資料
            </button>
            <button className="w-full rounded-lg bg-slate-800 py-2.5 text-sm font-medium text-slate-300 hover:bg-slate-700 transition-all">
              備份設定
            </button>
          </div>
        </div>
      </div>

      {/* 版本資訊 */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/20 p-6 shadow-panel">
        <div className="text-sm font-semibold">系統版本資訊</div>
        <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
          <div className="space-y-1">
            <div className="text-slate-400">前端版本</div>
            <div className="text-slate-300">v1.0.0 (Sprint 1)</div>
          </div>
          <div className="space-y-1">
            <div className="text-slate-400">後端版本</div>
            <div className="text-slate-300">v4.0.0</div>
          </div>
          <div className="space-y-1">
            <div className="text-slate-400">最後部署</div>
            <div className="text-slate-300">2026-02-28 19:15</div>
          </div>
          <div className="space-y-1">
            <div className="text-slate-400">開發模式</div>
            <div className="text-slate-300">24/7 極限開發</div>
          </div>
        </div>
      </div>
    </div>
  )
}
