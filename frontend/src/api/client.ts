import { isStaticMode } from './mode'
import { staticApi } from './staticClient'

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

// ---------------------------------------------------------------------------
// SSE narration (API mode only)
// ---------------------------------------------------------------------------

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
 * Only available in API mode — throws in static mode.
 */
export function narrateWorldStream(
  name: string,
  onDelta: (text: string) => void,
  onDone: (usage: NarrateUsage) => void,
  onError: (error: string) => void,
  options?: NarrateStreamOptions,
): () => void {
  if (isStaticMode()) {
    onError('AI narration is not available in static mode')
    return () => {}
  }

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

// ---------------------------------------------------------------------------
// Unified API object — delegates to static or live API based on mode
// ---------------------------------------------------------------------------

/** Write operations that are only available in API mode. */
const liveOnlyApi = {
  createWorld: (name: string, template: string = 'minimal', seed?: number) =>
    fetchJson<any>('/worlds', {
      method: 'POST',
      body: JSON.stringify({ name, template, seed }),
    }),

  deleteWorld: (name: string) =>
    fetchJson<void>(`/worlds/${name}`, { method: 'DELETE' }),

  validateWorld: (name: string) =>
    fetchJson<{ ok: boolean; errors: string[] }>(`/worlds/${name}/validate`),

  buildWorld: (name: string, engine?: string) =>
    fetchJson<{ status: string }>(`/worlds/${name}/build`, {
      method: 'POST',
      body: JSON.stringify({ engine }),
    }),
}

/** Read operations available in both modes. */
const readApi = {
  listWorlds: () =>
    isStaticMode() ? staticApi.listWorlds() : fetchJson<string[]>('/worlds'),

  getWorld: (name: string) =>
    isStaticMode() ? staticApi.getWorld(name) : fetchJson<any>(`/worlds/${name}`),

  getStellarSystem: (name: string, branch?: string | null) =>
    isStaticMode()
      ? staticApi.getStellarSystem(name)
      : fetchJson<any>(
          `/worlds/${name}/stellar${branch ? `?branch=${encodeURIComponent(branch)}` : ''}`,
        ),

  getPlanets: (name: string, branch?: string | null) =>
    isStaticMode()
      ? staticApi.getPlanets(name)
      : fetchJson<any[]>(
          `/worlds/${name}/planets${branch ? `?branch=${encodeURIComponent(branch)}` : ''}`,
        ),

  getHabitableZones: (name: string, branch?: string | null) =>
    isStaticMode()
      ? staticApi.getHabitableZones(name)
      : fetchJson<any>(
          `/worlds/${name}/habitable-zones${branch ? `?branch=${encodeURIComponent(branch)}` : ''}`,
        ),

  getPlanet: (name: string, planetId: string) =>
    isStaticMode()
      ? Promise.reject(new Error('getPlanet not available in static mode'))
      : fetchJson<any>(`/worlds/${name}/planets/${planetId}`),

  listBranches: (name: string) =>
    isStaticMode()
      ? staticApi.listBranches(name)
      : fetchJson<any[]>(`/worlds/${name}/branches`),
}

export const api = {
  ...readApi,

  // Write operations — only work in API mode, gracefully fail in static mode
  createWorld: (...args: Parameters<typeof liveOnlyApi.createWorld>) =>
    isStaticMode()
      ? Promise.reject(new Error('Not available in static mode'))
      : liveOnlyApi.createWorld(...args),

  deleteWorld: (...args: Parameters<typeof liveOnlyApi.deleteWorld>) =>
    isStaticMode()
      ? Promise.reject(new Error('Not available in static mode'))
      : liveOnlyApi.deleteWorld(...args),

  validateWorld: (...args: Parameters<typeof liveOnlyApi.validateWorld>) =>
    isStaticMode()
      ? Promise.reject(new Error('Not available in static mode'))
      : liveOnlyApi.validateWorld(...args),

  buildWorld: (...args: Parameters<typeof liveOnlyApi.buildWorld>) =>
    isStaticMode()
      ? Promise.reject(new Error('Not available in static mode'))
      : liveOnlyApi.buildWorld(...args),
}
