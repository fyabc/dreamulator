const API_BASE = '/api'

interface ApiResponse<T> {
  ok: boolean
  data: T
}

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${url}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    ...options,
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(error.detail || error.error || `HTTP ${response.status}`)
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return undefined as T
  }

  const body = await response.json()

  // Unwrap { ok, data } envelope if present
  if (body && typeof body === 'object' && 'ok' in body && 'data' in body) {
    return (body as ApiResponse<T>).data
  }

  return body as T
}

export const api = {
  // World operations
  listWorlds: () => fetchJson<string[]>('/worlds'),

  getWorld: (name: string) => fetchJson<any>(`/worlds/${name}`),

  createWorld: (name: string, template: string = 'minimal', seed?: number) =>
    fetchJson<any>('/worlds', {
      method: 'POST',
      body: JSON.stringify({ name, template, seed }),
    }),

  deleteWorld: (name: string) =>
    fetchJson<void>(`/worlds/${name}`, { method: 'DELETE' }),

  validateWorld: (name: string) =>
    fetchJson<{ ok: boolean; errors: string[] }>(`/worlds/${name}/validate`),

  // Build and simulation
  buildWorld: (name: string, engine?: string) =>
    fetchJson<{ status: string }>(`/worlds/${name}/build`, {
      method: 'POST',
      body: JSON.stringify({ engine }),
    }),

  // Data access
  getWorldData: (name: string, path: string) =>
    fetchJson<any>(`/worlds/${name}/data/${path}`),

  getStellarSystem: (name: string) =>
    fetchJson<any>(`/worlds/${name}/stellar`),

  getPlanets: (name: string) =>
    fetchJson<any[]>(`/worlds/${name}/planets`),

  getPlanet: (name: string, planetId: string) =>
    fetchJson<any>(`/worlds/${name}/planets/${planetId}`),
}
