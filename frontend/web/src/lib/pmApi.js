import { authFetch, getApiBase } from './auth'

export async function fetchPmStatus() {
  try {
    const res = await authFetch(`${getApiBase()}/api/pm/status`)
    if (res.ok) {
      const data = await res.json()
      return data.data
    }
  } catch { /* ignore */ }
  return null
}

export async function pmApprove(reason = '') {
  const res = await authFetch(`${getApiBase()}/api/pm/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  })
  if (!res.ok) throw new Error('授權失敗')
  return (await res.json()).data
}

export async function pmReject(reason = '') {
  const res = await authFetch(`${getApiBase()}/api/pm/reject`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  })
  if (!res.ok) throw new Error('封鎖失敗')
  return (await res.json()).data
}
