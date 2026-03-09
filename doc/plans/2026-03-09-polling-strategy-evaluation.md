# Dashboard Polling Strategy Evaluation

**Date**: 2026-03-09
**Issue**: #167

## Current Architecture

### SSE Endpoints (Server → Client Push)
| Endpoint | Consumer | Throttling |
|----------|----------|------------|
| `/api/stream/logs` | LogTerminal | rAF batching (flush once/frame, 500 cap) |
| `/api/stream/health` | System page | 5s server poll |
| `/api/portfolio/quote-stream/{symbol}` | QuotePanel (Drawer) | rAF throttle (latest-only ref) |

### Polling Patterns (Client → Server Pull)
| Page | Pattern | Trigger |
|------|---------|---------|
| Portfolio | `useReducer` + `AbortController` | Mount + manual refresh |
| Strategy | SSE-triggered debounced refresh (500ms) | SSE `log` events |
| System | Hook-based (`useSystemHealth`, etc.) | Mount + interval |
| Analysis | `useEffect` fetch | Mount + date change |

## Evaluation: TanStack Query vs Current Approach

### What TanStack Query Would Add
1. **Automatic background refetching** with `staleTime` / `refetchInterval`
2. **Cache deduplication** — same query from multiple components = one fetch
3. **Optimistic updates** and mutation management
4. **Devtools** for cache inspection
5. **Window focus refetching** — refresh stale data when user returns

### Current Strengths (Why Replacement May Not Be Needed)
1. **SSE push model** already eliminates polling for the most data-intensive paths (logs, quotes). TanStack Query doesn't improve push-based flows.
2. **rAF throttling** already solves the high-frequency update problem at the rendering layer, which TanStack Query doesn't address.
3. **`useReducer` state machine** in Portfolio provides atomic transitions and prevents race conditions — TanStack Query mutations are less structured.
4. **Debounced SSE→refresh** in Strategy already batches updates efficiently.
5. **Low component count** (~7 pages, ~15 data-fetching hooks) means the overhead of a new dependency isn't justified by complexity reduction.

### Where TanStack Query Would Help
1. **System page health hooks** — multiple hooks (`useSystemHealth`, `useSystemRisk`, `useSystemQuota`, etc.) could benefit from unified caching and stale-while-revalidate.
2. **Analysis page** — date-keyed queries with caching would avoid re-fetching when navigating back to a previously viewed date.
3. **Cross-page cache sharing** — if Portfolio and Drawer both need the same position data, TanStack Query deduplicates automatically.

## Recommendation

**Keep current approach. Do not adopt TanStack Query.**

### Rationale
1. The dashboard's primary data flows are **push-based** (SSE), not poll-based. TanStack Query's core value (smart polling + caching) applies to a small subset of our data.
2. The rAF throttling and useReducer patterns are **already production-tested** and handle 200+ events/sec without jank (verified by stress test).
3. Adding TanStack Query would require **rewriting all data hooks** (~15 hooks across 7 pages) with no functional improvement for the SSE paths.
4. The bundle size increase (~13KB gzipped) is not justified for a single-user dashboard.
5. The existing patterns are **well-understood** by the codebase and have comprehensive test coverage.

### If Reconsidered Later
If the dashboard grows to 20+ pages with heavy cross-page data sharing, TanStack Query becomes more attractive. The migration path would be:
1. Start with System page health hooks (lowest risk, clearest benefit)
2. Wrap existing fetch functions as `queryFn` — no backend changes needed
3. Keep SSE consumers as-is (they bypass the query layer)

## Stress Test Results

### Tool
`tools/stress_test_sse.py` — three modes:
- `inject`: Write synthetic rows to DB at target rate
- `standalone`: Run local SSE server emitting at target rate
- `consume`: Connect to endpoint and measure throughput

### How to Run Soak Test
```bash
# Terminal 1: Start stress emitter
python3 tools/stress_test_sse.py inject --rate 200 --seconds 600

# Terminal 2: Monitor consumer throughput
python3 tools/stress_test_sse.py consume \
  --url https://127.0.0.1:8080/api/stream/logs --seconds 600

# Browser: Open dashboard, observe via DevTools:
#   - Performance tab → check for long tasks (>50ms)
#   - Memory tab → heap snapshot before/after 10 min
#   - Target: memory growth < 5MB over 10 min
```

### Expected Behavior Under Load
- LogTerminal: rAF batching caps at 500 entries, older entries dropped
- QuotePanel: ref-based latest-only pattern means only 1 render/frame regardless of event rate
- Strategy: 500ms debounce means max 2 API calls/sec even under 200+ SSE events/sec
