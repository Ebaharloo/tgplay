// The whole API surface, two functions: the server always answers JSON.
export async function get(path) {
  const r = await fetch(path)
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.error || `${r.status} ${r.statusText}`)
  return data
}

export async function post(path, body = {}) {
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.error || `${r.status} ${r.statusText}`)
  return data
}
