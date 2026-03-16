import React from 'react'
import { GitBranch, CheckCircle2, XCircle } from 'lucide-react'
import { formatCurrency } from '../../lib/format'
import DetailSection from './DetailSection'

/** 單一鏈節點 */
function ChainStep({ step, label, color, content }) {
    const dotColor = {
        indigo: 'bg-indigo-500',
        emerald: 'bg-emerald-500',
        rose: 'bg-rose-500',
        slate: 'bg-slate-500',
    }[color] || 'bg-slate-500'

    return (
        <div className="flex gap-3">
            <div className="flex flex-col items-center">
                <div className={`flex h-6 w-6 items-center justify-center rounded-full ${dotColor} text-[10px] font-bold text-white flex-shrink-0`}>
                    {step}
                </div>
                <div className="mt-1 w-px flex-1 bg-slate-800" />
            </div>
            <div className="pb-3 flex-1 min-w-0">
                <div className="text-xs font-semibold text-slate-300 mb-1.5">{label}</div>
                {content}
            </div>
        </div>
    )
}

/** 決策鏈 section：strategy → risk_check → fills */
export default function DecisionChainPanel({ decision, riskCheck, fills }) {
    return (
        <DetailSection icon={GitBranch} title="決策鏈">
            <div className="space-y-3">
                {/* Strategy decision */}
                <ChainStep
                    step="1"
                    label="策略決策"
                    color="indigo"
                    content={
                        decision ? (
                            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                                <span className="text-slate-500">策略</span>
                                <span className="text-indigo-300 font-mono">{decision.strategy_id || '-'}</span>
                                <span className="text-slate-500">版本</span>
                                <span className="text-slate-300">{decision.strategy_version || '-'}</span>
                                <span className="text-slate-500">方向</span>
                                <span className={`font-semibold ${decision.signal_side === 'buy' ? 'text-emerald-300' : 'text-rose-300'}`}>
                                    {decision.signal_side?.toUpperCase() || '-'}
                                </span>
                                <span className="text-slate-500">信心分</span>
                                <span className="text-amber-300">{decision.signal_score ?? '-'}</span>
                                <span className="text-slate-500">時間</span>
                                <span className="text-slate-400">{decision.ts ? new Date(decision.ts).toLocaleString('zh-TW', { hour12: false }) : '-'}</span>
                            </div>
                        ) : (
                            <span className="text-slate-500 text-xs">暫無決策記錄</span>
                        )
                    }
                />

                {/* Risk check */}
                <ChainStep
                    step="2"
                    label="風控核驗"
                    color={riskCheck?.passed ? 'emerald' : 'rose'}
                    content={
                        riskCheck ? (
                            <div className="flex items-center gap-3 text-xs">
                                {riskCheck.passed
                                    ? <CheckCircle2 className="h-4 w-4 text-emerald-400 flex-shrink-0" />
                                    : <XCircle className="h-4 w-4 text-rose-400 flex-shrink-0" />
                                }
                                <span className={riskCheck.passed ? 'text-emerald-300' : 'text-rose-300'}>
                                    {riskCheck.passed ? '通過' : `拒絕：${riskCheck.reject_code || '未知'}`}
                                </span>
                                {riskCheck.metrics?.orders_last_60s != null && (
                                    <span className="text-slate-500">60s 訂單數：{riskCheck.metrics.orders_last_60s}</span>
                                )}
                            </div>
                        ) : (
                            <span className="text-slate-500 text-xs">暫無風控記錄</span>
                        )
                    }
                />

                {/* Fills */}
                <ChainStep
                    step="3"
                    label="成交明細"
                    color="slate"
                    content={
                        fills && fills.length > 0 ? (
                            <div className="space-y-1">
                                <div className="grid grid-cols-4 gap-2 text-[11px] text-slate-500 font-medium">
                                    <span>時間</span>
                                    <span>數量</span>
                                    <span>價格</span>
                                    <span>手續費</span>
                                </div>
                                {fills.map((f, i) => (
                                    <div key={f.fill_id || i} className="grid grid-cols-4 gap-2 text-xs">
                                        <span className="text-slate-400">
                                            {f.ts ? new Date(f.ts).toLocaleTimeString('zh-TW', { hour12: false }) : '-'}
                                        </span>
                                        <span className="text-slate-200">{f.qty}</span>
                                        <span className="text-slate-200">{formatCurrency(f.price)}</span>
                                        <span className="text-slate-400">{f.fee ? formatCurrency(f.fee) : '0'}</span>
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <span className="text-slate-500 text-xs">暫無成交記錄</span>
                        )
                    }
                />
            </div>
        </DetailSection>
    )
}
