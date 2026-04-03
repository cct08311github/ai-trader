import React from 'react'

/**
 * AlertBadge — alert level indicator with optional action button
 * level: 'red' | 'yellow' | 'green'
 */
export function AlertBadge({ level = 'yellow', message, actionLabel, onAction }) {
  const config = {
    red: {
      borderVar: 'rgb(var(--danger))',
      textVar: 'rgb(var(--danger))',
      bgVar: 'rgba(var(--danger), 0.08)',
      className: 'animate-lava-pulse',
      icon: '!',
    },
    yellow: {
      borderVar: 'rgb(var(--warn))',
      textVar: 'rgb(var(--warn))',
      bgVar: 'rgba(var(--warn), 0.08)',
      className: '',
      icon: '⚠',
    },
    green: {
      borderVar: 'rgb(var(--up))',
      textVar: 'rgb(var(--up))',
      bgVar: 'rgba(var(--up), 0.06)',
      className: '',
      icon: '✓',
    },
  }

  const { borderVar, textVar, bgVar, className, icon } = config[level] ?? config.yellow

  return (
    <div
      className={`
        flex items-start gap-2 px-3 py-2 rounded-sm border
        ${className}
      `}
      style={{
        borderColor: borderVar,
        backgroundColor: bgVar,
      }}
    >
      <span
        className="text-xs font-bold flex-shrink-0 mt-px"
        style={{ color: textVar, fontFamily: 'var(--font-mono)' }}
      >
        {icon}
      </span>
      <span
        className="text-xs flex-1"
        style={{ color: textVar, fontFamily: 'var(--font-ui)' }}
      >
        {message}
      </span>
      {actionLabel && onAction && (
        <button
          onClick={onAction}
          className="text-xs px-2 py-0.5 rounded-sm border flex-shrink-0 transition-opacity hover:opacity-80"
          style={{
            color: textVar,
            borderColor: borderVar,
            fontFamily: 'var(--font-mono)',
          }}
        >
          {actionLabel}
        </button>
      )}
    </div>
  )
}

export default AlertBadge
