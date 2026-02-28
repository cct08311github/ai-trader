import '@testing-library/jest-dom'
import { expect } from 'vitest'
import { toHaveNoViolations } from 'jest-axe'

expect.extend(toHaveNoViolations)

class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

if (typeof window !== 'undefined' && !window.ResizeObserver) {
  window.ResizeObserver = ResizeObserver
}

// Help Recharts calculate non-zero container size in jsdom.
if (typeof window !== 'undefined') {
  const parsePx = (v) => {
    if (!v) return 0
    const m = String(v).match(/(\d+(?:\.\d+)?)px/)
    return m ? Number(m[1]) : 0
  }

  // eslint-disable-next-line no-extend-native
  HTMLElement.prototype.getBoundingClientRect = function getBoundingClientRect() {
    const w = parsePx(this.style?.width) || 800
    const h = parsePx(this.style?.height) || 300
    return {
      x: 0,
      y: 0,
      top: 0,
      left: 0,
      right: w,
      bottom: h,
      width: w,
      height: h,
      toJSON() {}
    }
  }
}
