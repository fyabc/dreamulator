import { isStaticMode } from './mode'
import { staticApi } from './staticClient'
import type { CVTMesh, CVTVertex, CVTRegion, VoronoiCell } from '../viewers/map/types'

const API_BASE = '/api'

// ---------------------------------------------------------------------------
// CVT mesh adapter — converts backend raw format to frontend typed format
// ---------------------------------------------------------------------------

/**
 * Adapt the raw backend CVT mesh JSON to the frontend CVTMesh type.
 *
 * Backend sends:
 * - vertices: [[x,y,z], ...] — raw 3D Cartesian arrays on unit sphere
 * - regions:  [[v0,v1,...], ...] — raw vertex index arrays
 * - cells:    VoronoiCell objects (full property set)
 *
 * Frontend expects:
 * - vertices: CVTVertex[] — {id, lon, lat}
 * - regions:  CVTRegion[] — {id, vertex_ids, plate_id, boundaries}
 */
function adaptCvtMesh(raw: any): CVTMesh | null {
  if (!raw || !raw.cells) return null

  // Convert vertices: [x,y,z] → {id, lon, lat}
  const vertices: CVTVertex[] = (raw.vertices || []).map(
    (v: number[], i: number) => {
      const [x, y, z] = v
      const r = Math.sqrt(x * x + y * y + z * z)
      const lat =
        Math.asin(Math.max(-1, Math.min(1, y / Math.max(r, 1e-12)))) *
        (180 / Math.PI)
      const lon = Math.atan2(z, x) * (180 / Math.PI)
      return { id: i, lon, lat }
    },
  )

  // Convert regions: [v0,v1,...] → {id, vertex_ids, plate_id, boundaries}
  const regions: CVTRegion[] = (raw.regions || []).map(
    (r: number[], i: number) => ({
      id: i,
      vertex_ids: r,
      plate_id: (raw.cells[i] as VoronoiCell | undefined)?.plate_id ?? null,
      boundaries: null,
    }),
  )

  return {
    seed: raw.seed ?? 0,
    num_cells: raw.num_cells ?? 0,
    jitter_sigma: raw.jitter_sigma,
    lloyd_iterations: raw.lloyd_iterations,
    cells: (raw.cells ?? []) as VoronoiCell[],
    adjacency: (raw.adjacency ?? {}) as Record<string, number[]>,
    vertices,
    regions,
  }
}

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

/** Fetch a binary blob from the API. */
async function fetchBlob(url: string): Promise<Blob> {
  const response = await fetch(`${API_BASE}${url}`)
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(error.detail || `HTTP ${response.status}`)
  }
  return response.blob()
}

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

  // ---- Map write operations ----

  saveElevation: (world: string, planetId: string, pngBlob: Blob, branch?: string | null) => {
    const formData = new FormData()
    formData.append('file', pngBlob, 'elevation.png')
    const params = branch ? `?branch=${encodeURIComponent(branch)}` : ''
    return fetch(`/api/worlds/${world}/maps/${planetId}/elevation${params}`, {
      method: 'POST',
      body: formData,
    }).then((r) => r.json())
  },

  importElevation: (world: string, planetId: string, file: File, branch?: string | null) => {
    const formData = new FormData()
    formData.append('file', file)
    const params = branch ? `?branch=${encodeURIComponent(branch)}` : ''
    return fetch(`/api/worlds/${world}/maps/${planetId}/import-elevation${params}`, {
      method: 'POST',
      body: formData,
    }).then((r) => r.json())
  },

  saveVoronoi: (world: string, planetId: string, network: any, branch?: string | null) => {
    const params = branch ? `?branch=${encodeURIComponent(branch)}` : ''
    return fetchJson<any>(`/worlds/${world}/maps/${planetId}/voronoi${params}`, {
      method: 'POST',
      body: JSON.stringify(network),
    })
  },

  savePlates: (world: string, planetId: string, plates: any[], branch?: string | null) => {
    const params = branch ? `?branch=${encodeURIComponent(branch)}` : ''
    return fetchJson<any>(`/worlds/${world}/maps/${planetId}/plates${params}`, {
      method: 'POST',
      body: JSON.stringify(plates),
    })
  },

  generateTerrain: (
    world: string,
    planetId: string,
    params: Record<string, any> = {},
    branch?: string | null,
  ) => {
    const qs = branch ? `?branch=${encodeURIComponent(branch)}` : ''
    return fetchJson<any>(`/worlds/${world}/maps/${planetId}/generate${qs}`, {
      method: 'POST',
      body: JSON.stringify(params),
    })
  },

  deleteMap: (world: string, planetId: string, branch?: string | null) => {
    const params = branch ? `?branch=${encodeURIComponent(branch)}` : ''
    return fetchJson<void>(`/worlds/${world}/maps/${planetId}${params}`, {
      method: 'DELETE',
    })
  },
}

/** Read operations available in both modes. */
const readApi = {
  listWorlds: () =>
    isStaticMode() ? staticApi.listWorlds() : fetchJson<string[]>('/worlds'),

  getWorld: (name: string) =>
    isStaticMode() ? staticApi.getWorld(name) : fetchJson<any>(`/worlds/${name}`),

  getStellarSystem: (name: string, branch?: string | null) =>
    isStaticMode()
      ? staticApi.getStellarSystem(name, branch)
      : fetchJson<any>(
          `/worlds/${name}/stellar${branch ? `?branch=${encodeURIComponent(branch)}` : ''}`,
        ),

  getPlanets: (name: string, branch?: string | null) =>
    isStaticMode()
      ? staticApi.getPlanets(name, branch)
      : fetchJson<any[]>(
          `/worlds/${name}/planets${branch ? `?branch=${encodeURIComponent(branch)}` : ''}`,
        ),

  getHabitableZones: (name: string, branch?: string | null) =>
    isStaticMode()
      ? staticApi.getHabitableZones(name, branch)
      : fetchJson<any>(
          `/worlds/${name}/habitable-zones${branch ? `?branch=${encodeURIComponent(branch)}` : ''}`,
        ),

  getClimate: (name: string, branch?: string | null) =>
    isStaticMode()
      ? staticApi.getClimate(name, branch)
      : fetchJson<any>(
          `/worlds/${name}/climate${branch ? `?branch=${encodeURIComponent(branch)}` : ''}`,
        ),

  getEcology: (name: string, branch?: string | null) =>
    isStaticMode()
      ? staticApi.getEcology(name, branch)
      : fetchJson<any>(
          `/worlds/${name}/ecology${branch ? `?branch=${encodeURIComponent(branch)}` : ''}`,
        ),

  getPlanet: (name: string, planetId: string) =>
    isStaticMode()
      ? Promise.reject(new Error('getPlanet not available in static mode'))
      : fetchJson<any>(`/worlds/${name}/planets/${planetId}`),

  listBranches: (name: string) =>
    isStaticMode()
      ? staticApi.listBranches(name)
      : fetchJson<any[]>(`/worlds/${name}/branches`),

  // Legacy civilization document methods (delegate to generic layer-documents)
  listCivilizationDocuments: (name: string, branch?: string | null) =>
    readApi.listLayerDocuments(name, 'civilization', branch),

  getCivilizationDocument: (name: string, filename: string, branch?: string | null) =>
    readApi.getLayerDocument(name, 'civilization', filename, branch),

  // ---- Layer documents (generalized for any layer) ----

  listLayerDocuments: (name: string, layer: string, branch?: string | null) =>
    isStaticMode()
      ? staticApi.listLayerDocuments(name, layer, branch)
      : fetchJson<any[]>(
          `/worlds/${name}/layer-documents/${layer}${branch ? `?branch=${encodeURIComponent(branch)}` : ''}`,
        ),

  getLayerDocument: (name: string, layer: string, filename: string, branch?: string | null) =>
    isStaticMode()
      ? staticApi.getLayerDocument(name, layer, filename, branch)
      : fetchJson<any>(
          `/worlds/${name}/layer-documents/${layer}/${encodeURIComponent(filename)}${branch ? `?branch=${encodeURIComponent(branch)}` : ''}`,
        ),

  // ---- Design documents (non-layer, cross-cutting design notes) ----

  listDesignDocuments: (name: string, branch?: string | null) =>
    isStaticMode()
      ? staticApi.listDesignDocuments(name, branch)
      : fetchJson<any[]>(
          `/worlds/${name}/design-documents${branch ? `?branch=${encodeURIComponent(branch)}` : ''}`,
        ),

  getDesignDocument: (name: string, filename: string, branch?: string | null) =>
    isStaticMode()
      ? staticApi.getDesignDocument(name, filename, branch)
      : fetchJson<any>(
          `/worlds/${name}/design-documents/${encodeURIComponent(filename)}${branch ? `?branch=${encodeURIComponent(branch)}` : ''}`,
        ),

  // ---- Map read operations ----

  listMapPlanets: (name: string, branch?: string | null) =>
    isStaticMode()
      ? staticApi.listMapPlanets(name, branch)
      : fetchJson<string[]>(
          `/worlds/${name}/maps${branch ? `?branch=${encodeURIComponent(branch)}` : ''}`,
        ),

  getMapMeta: (name: string, planetId: string, branch?: string | null) =>
    isStaticMode()
      ? staticApi.getMapMeta(name, planetId, branch)
      : fetchJson<any>(
          `/worlds/${name}/maps/${planetId}/meta${branch ? `?branch=${encodeURIComponent(branch)}` : ''}`,
        ),

  getElevationBlob: (name: string, planetId: string, branch?: string | null) =>
    isStaticMode()
      ? staticApi.getElevationBlob(name, planetId, branch)
      : fetchBlob(
          `/worlds/${name}/maps/${planetId}/elevation${branch ? `?branch=${encodeURIComponent(branch)}` : ''}`,
        ),

  getVoronoi: (name: string, planetId: string, branch?: string | null) =>
    isStaticMode()
      ? staticApi.getVoronoi(name, planetId, branch)
      : fetchJson<any>(
          `/worlds/${name}/maps/${planetId}/voronoi${branch ? `?branch=${encodeURIComponent(branch)}` : ''}`,
        ),

  getPlates: (name: string, planetId: string, branch?: string | null) =>
    isStaticMode()
      ? staticApi.getPlates(name, planetId, branch)
      : fetchJson<any[]>(
          `/worlds/${name}/maps/${planetId}/plates${branch ? `?branch=${encodeURIComponent(branch)}` : ''}`,
        ),

  getFeatures: (name: string, planetId: string, branch?: string | null) =>
    isStaticMode()
      ? staticApi.getFeatures(name, planetId, branch)
      : fetchJson<any[]>(
          `/worlds/${name}/maps/${planetId}/features${branch ? `?branch=${encodeURIComponent(branch)}` : ''}`,
        ),

  getMapLayer: (name: string, planetId: string, layerType: string, branch?: string | null) =>
    isStaticMode()
      ? Promise.reject(new Error('Derived map layers not available in static mode'))
      : fetchBlob(
          `/worlds/${name}/maps/${planetId}/layer/${layerType}${branch ? `?branch=${encodeURIComponent(branch)}` : ''}`,
        ),

  getCvtMesh: (name: string, planetId: string, branch?: string | null): Promise<CVTMesh | null> =>
    isStaticMode()
      ? staticApi.getCvtMesh(name, planetId, branch).then(adaptCvtMesh)
      : fetchJson<any>(
          `/worlds/${name}/maps/${planetId}/cvt-mesh${branch ? `?branch=${encodeURIComponent(branch)}` : ''}`,
        ).then(adaptCvtMesh),
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

  // Map write operations
  saveElevation: (...args: Parameters<typeof liveOnlyApi.saveElevation>) =>
    isStaticMode()
      ? Promise.reject(new Error('Not available in static mode'))
      : liveOnlyApi.saveElevation(...args),

  importElevation: (...args: Parameters<typeof liveOnlyApi.importElevation>) =>
    isStaticMode()
      ? Promise.reject(new Error('Not available in static mode'))
      : liveOnlyApi.importElevation(...args),

  saveVoronoi: (...args: Parameters<typeof liveOnlyApi.saveVoronoi>) =>
    isStaticMode()
      ? Promise.reject(new Error('Not available in static mode'))
      : liveOnlyApi.saveVoronoi(...args),

  savePlates: (...args: Parameters<typeof liveOnlyApi.savePlates>) =>
    isStaticMode()
      ? Promise.reject(new Error('Not available in static mode'))
      : liveOnlyApi.savePlates(...args),

  generateTerrain: (...args: Parameters<typeof liveOnlyApi.generateTerrain>) =>
    isStaticMode()
      ? Promise.reject(new Error('Not available in static mode'))
      : liveOnlyApi.generateTerrain(...args),

  deleteMap: (...args: Parameters<typeof liveOnlyApi.deleteMap>) =>
    isStaticMode()
      ? Promise.reject(new Error('Not available in static mode'))
      : liveOnlyApi.deleteMap(...args),
}


