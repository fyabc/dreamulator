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

export interface NarrateUsage {
  input_tokens: number
  output_tokens: number
  total_tokens: number
}

export interface NarrateStreamOptions {
  branch?: string
  model?: string
  maxTokens?: number
}

/**
 * Stream narration for a world via SSE.
 * Returns a cleanup function that aborts the stream when called.
 */
export function narrateWorldStream(
  name: string,
  onDelta: (text: string) => void,
  onDone: (usage: NarrateUsage) => void,
  onError: (error: string) => void,
  options?: NarrateStreamOptions,
): () => void {
  const controller = new AbortController()

  ;(async () => {
    try {
      const response = await fetch(`${API_BASE}/worlds/${name}/narrate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          branch: options?.branch ?? null,
          model: options?.model ?? null,
          max_tokens: options?.maxTokens ?? 32768,
        }),
        signal: controller.signal,
      })

      if (!response.ok) {
        const error = await response
          .json()
          .catch(() => ({ detail: 'Unknown error' }))
        onError(error.detail || `HTTP ${response.status}`)
        return
      }

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const events = buffer.split('\n\n')
        buffer = events.pop() || ''

        for (const event of events) {
          if (!event.trim() || event.startsWith(':')) continue

          const typeMatch = event.match(/^event:\s*(.+)$/m)
          const dataMatch = event.match(/^data:\s*(.+)$/m)
          if (!typeMatch || !dataMatch) continue

          const eventType = typeMatch[1].trim()
          const data = JSON.parse(dataMatch[1])

          if (eventType === 'delta') {
            onDelta(data.text)
          } else if (eventType === 'done') {
            onDone(data as NarrateUsage)
          } else if (eventType === 'error') {
            onError(data.detail || 'Unknown error')
          }
        }
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      onError(err instanceof Error ? err.message : String(err))
    }
  })()

  return () => controller.abort()
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

  // Branches
  listBranches: (name: string) =>
    fetchJson<any[]>(`/worlds/${name}/branches`),
}
