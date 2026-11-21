/**
 * Static data client — reads pre-exported JSON from /data/.
 *
 * Used for GitHub Pages deployment where no backend is available.
 * Only supports read operations; write operations throw.
 */

import type { BuildGrid, BuildJob } from './buildJobs'
import type { SystemCatalog } from './catalogAdapter'
import type { CivTerritory, GeoBoundaryCollection } from '../components/civmap/types'
import type { RegionRefinementSource } from '../viewers/packs/types'
import type { MapResultMetadata } from './resultContract'
import { decodeMonthlyClimate, type MonthlyClimateData } from './monthlyClimate'
import { decodeYearlyClimate, type YearlyClimateData } from './yearlyClimate'
import type { StarterFiles, StarterSettings, StarterTemplate } from '../projects/starterWorld'
import type { WorldParameters, WorldParameterUpdate } from './worldParameters'
import type { ParameterDefaults } from '../projects/worldParameters'
import type { ClimateTrialForcing } from './climateTrials'
import type { BrowserEbmSource } from '../playground/browserEbm'

interface DocumentMeta {
  filename: string
  title: string
  type: string
  period?: string
  tags?: string[]
  status?: string
  date?: string
}

// Vite replaces BASE_URL at build time with the configured base path
// e.g. '/' for local preview, '/dreamulator/' for GitHub Pages
const DATA_BASE = `${import.meta.env.BASE_URL}data`

// Data URLs are NOT content-hashed, so use conditional revalidation
// (cache: 'no-cache') instead of trusting the browser cache: GitHub Pages
// serves 200s with max-age=600 (stale data after redeploy) and 404s with
// no Cache-Control at all (undefined browser caching — stale 404 replays
// were observed to break map loading). Revalidation costs one cheap
// conditional request per file; unchanged large meshes answer 304.
const FETCH_INIT: RequestInit = { cache: 'no-cache' }

async function browserEbmSource(world: string, planet: string, branch: string | null, signal?: AbortSignal) {
  const scope = `/worlds/${encodeURIComponent(world)}${branch ? `/branches/${encodeURIComponent(branch)}` : ''}`
  const directory = `${DATA_BASE}${scope}/maps/${encodeURIComponent(planet)}/`
  const response = await fetch(`${directory}climate_trial.json`, { ...FETCH_INIT, signal })
  if (response.status === 404 || response.headers.get('content-type')?.includes('text/html')) {
    throw new Error('browser_unavailable')
  }
  if (!response.ok) throw new Error('browser_source')
  const data = await response.json() as { version: number } & (BrowserEbmSource | { reason: string })
  if (data.version !== 1) throw new Error('browser_unavailable')
  if ('reason' in data) throw new Error(data.reason)
  if (!['cvt_mesh.msgpack.gz', 'climate_trial_mesh.bin'].includes(data.mesh) || !data.config ||
      !data.forcing || !Number.isInteger(data.cells) || data.cells < 1) throw new Error('browser_source')
  if (typeof Worker === 'undefined' || typeof WebAssembly === 'undefined' || typeof DecompressionStream === 'undefined') {
    throw new Error('browser_incompatible')
  }
  return { ...data, mesh: new URL(`${directory}${data.mesh}`, document.baseURI).href }
}

async function fetchStaticJson<T>(path: string, onMissing?: () => T): Promise<T> {
  const response = await fetch(`${DATA_BASE}${path}`, FETCH_INIT)
  if (response.status === 404 && onMissing) return onMissing()
  if (!response.ok) {
    throw new Error(`Static data not found: ${path} (HTTP ${response.status})`)
  }
  return response.json() as Promise<T>
}

async function fetchStaticBlob(path: string): Promise<Blob> {
  const response = await fetch(`${DATA_BASE}${path}`, FETCH_INIT)
  if (!response.ok) {
    throw new Error(`Static data not found: ${path} (HTTP ${response.status})`)
  }
  return response.blob()
}

/**
 * Try fetching JSON from the branch path first, then fall back to root.
 * Returns null if neither path has the data.
 */
async function fetchBranchAwareJson<T>(
  name: string,
  branch: string | null | undefined,
  branchPath: string,
  rootPath: string,
): Promise<T | null> {
  if (branch) {
    try {
      return await fetchStaticJson<T>(`/worlds/${name}/branches/${branch}${branchPath}`)
    } catch {
      // Fall through to root
    }
  }
  try {
    return await fetchStaticJson<T>(`/worlds/${name}${rootPath}`)
  } catch {
    return null
  }
}

async function fetchBranchAwareBlob(
  name: string,
  branch: string | null | undefined,
  branchPath: string,
  rootPath: string,
): Promise<Blob | null> {
  if (branch) {
    try {
      return await fetchStaticBlob(`/worlds/${name}/branches/${branch}${branchPath}`)
    } catch {
      // Fall through to root
    }
  }
  try {
    return await fetchStaticBlob(`/worlds/${name}${rootPath}`)
  } catch {
    return null
  }
}

/**
 * Fetch the CVT mesh for a planet, split pair first, combined second.
 *
 * 0. ``mesh_geometry.msgpack.gz`` + ``mesh_fields.msgpack.gz`` (2026-09-29
 *    split export) — columnar blobs, worker-decoded and transferred
 *    zero-copy; returns ``{ geo, flds }`` for composeSplitMesh.
 * 1. ``cvt_mesh.msgpack.gz`` (combined) — fetched as a blob, handed
 *    to the shared MessagePack worker as an object URL with gunzip: true,
 *    so neither the gzip decompression nor the decode touches the main
 *    thread (the legacy path JSON.parsed the whole mesh on the main thread).
 * 2. ``cvt_mesh.json`` (pre-migration exports) — plain JSON, main thread.
 *
 * Returns null when neither generation exists (caller decides the fallback).
 */
async function fetchBranchAwareMesh(
  name: string,
  branch: string | null | undefined,
  planetId: string,
): Promise<any | null> {
  // Split pair (both halves or none — the export writes them together).
  const geoPath = `/maps/${planetId}/mesh_geometry.msgpack.gz`
  const fldsPath = `/maps/${planetId}/mesh_fields.msgpack.gz`
  try {
    const [geoBlob, fldsBlob] = await Promise.all([
      fetchBranchAwareBlob(name, branch, geoPath, geoPath),
      fetchBranchAwareBlob(name, branch, fldsPath, fldsPath),
    ])
    if (geoBlob !== null && fldsBlob !== null) {
      const { decodeMsgpackUrl } = await import('../workers/msgpackClient')
      const { isSplitFields, isSplitGeometry } = await import('./meshColumns')
      const geoUrl = URL.createObjectURL(geoBlob)
      const fldsUrl = URL.createObjectURL(fldsBlob)
      try {
        const [geo, flds] = await Promise.all([
          decodeMsgpackUrl(geoUrl, true),
          decodeMsgpackUrl(fldsUrl, true),
        ])
        if (isSplitGeometry(geo) && isSplitFields(flds)) {
          return { __split: true, geo, flds }
        }
      } finally {
        URL.revokeObjectURL(geoUrl)
        URL.revokeObjectURL(fldsUrl)
      }
    }
  } catch {
    // fall through to the combined path
  }
  const meshPath = `/maps/${planetId}/cvt_mesh.msgpack.gz`
  const blob = await fetchBranchAwareBlob(name, branch, meshPath, meshPath)
  if (blob !== null) {
    const { decodeMsgpackUrl } = await import('../workers/msgpackClient')
    const objectUrl = URL.createObjectURL(blob)
    try {
      return await decodeMsgpackUrl(objectUrl, true)
    } finally {
      URL.revokeObjectURL(objectUrl)
    }
  }
  const legacyPath = `/maps/${planetId}/cvt_mesh.json`
  return fetchBranchAwareJson<any>(name, branch, legacyPath, legacyPath)
}

function notAvailable(operation: string): never {
  throw new Error(`${operation} is not available in static mode`)
}

export interface StaticNarrateUsage {
  input_tokens: number
  output_tokens: number
  total_tokens: number
}

async function saveCreationWorld(id: string, title: string, archive: Blob, creationKind?: 'starter') {
  const { addProject } = await import('../projects/projectStore')
  const published = await staticApi.listWorlds()
  if (published.some(world => world.toLowerCase() === id)) throw new DOMException('This world ID is already in use', 'ConstraintError')
  return { id: await addProject({ id, name: title, updatedAt: Date.now(), layers: [], creationSnapshot: archive, creationKind }) }
}

export const staticApi = {
  async getWorldParameters(id: string, branch: string | null): Promise<WorldParameters> {
    const { getProject } = await import('../projects/projectStore')
    const project = await getProject(id)
    if (project && !project.published && id !== 'earth') {
      const defaults = await fetchStaticJson<ParameterDefaults>('/world-grid-defaults.json')
      if (project.creationSnapshot && !branch) {
        const { readBrowserParameters } = await import('../projects/worldParameters')
        return readBrowserParameters(project.creationSnapshot, defaults, String(project.updatedAt))
      }
      return { ...defaults, num_cells: null, built_cells: null, source: null, revision: null,
        reuses_mesh: false, read_only: 'unavailable', planet: null }
    }
    const root = `/worlds/${encodeURIComponent(id)}`
    const scope = branch ? `${root}/branches/${encodeURIComponent(branch)}` : root
    return fetchStaticJson<WorldParameters>(`${scope}/world-parameters.json`)
  },
  async saveWorldParameters(id: string, branch: string | null, settings: WorldParameterUpdate) {
    const { getProject, updateProject } = await import('../projects/projectStore')
    const project = await getProject(id)
    if (id === 'earth' || !project?.creationSnapshot || project.published || branch) throw new Error('Read-only world')
    if (settings.revision !== String(project.updatedAt)) throw new DOMException('World changed', 'InvalidStateError')
    const [{ writeBrowserParameters }, defaults] = await Promise.all([
      import('../projects/worldParameters'), fetchStaticJson<ParameterDefaults>('/world-grid-defaults.json'),
    ])
    const archive = await writeBrowserParameters(project.creationSnapshot, settings, defaults)
    await updateProject(id, current => {
      if (current.updatedAt !== project.updatedAt || current.published || !current.creationSnapshot) {
        throw new DOMException('World changed', 'InvalidStateError')
      }
      return { ...current, creationSnapshot: archive }
    })
    return staticApi.getWorldParameters(id, branch)
  },
  saveHeightmapWorld: saveCreationWorld,
  async saveStarterWorld(settings: StarterSettings) {
    const [{ exportStarterWorld }, templates] = await Promise.all([import('../projects/starterWorld'),
      fetchStaticJson<Record<StarterTemplate, StarterFiles>>('/starter-templates.json')])
    const archive = await exportStarterWorld(settings, templates[settings.template], new Date().toISOString())
    return saveCreationWorld(settings.id, settings.title, archive, 'starter')
  },
  async restoreCreationWorld(archive: Blob) {
    const [{ readCreationSnapshot }, { heightmapCreationPath, readHeightmapSnapshot }] = await Promise.all([
      import('../projects/creationSnapshot'), import('../projects/heightmapWorld'),
    ])
    const snapshot = await readCreationSnapshot(archive)
    if (snapshot.files.has(heightmapCreationPath)) {
      const { id, title } = await readHeightmapSnapshot(snapshot)
      return saveCreationWorld(id, title, archive)
    }
    const { readStarterSnapshot } = await import('../projects/starterWorld')
    const { id, title } = await readStarterSnapshot(snapshot)
    return saveCreationWorld(id, title, archive, 'starter')
  },
  async getHeightmapWorld(id: string) {
    const { getProject } = await import('../projects/projectStore')
    const project = await getProject(id)
    const archive = project?.creationKind !== 'starter' ? project?.creationSnapshot : undefined
    return archive ? (await import('../projects/heightmapWorld')).importHeightmapWorld(archive) : null
  },
  // World operations (read-only)
  listWorlds: () => fetchStaticJson<string[]>('/worlds.json'),

  getWorld: (name: string) => fetchStaticJson<any>(`/worlds/${name}/world.json`),

  getWorldSnapshotUrl: (): null => null,

  // Write operations — not available in static mode
  createWorld: () => notAvailable('createWorld'),
  deleteWorld: () => notAvailable('deleteWorld'),
  validateWorld: () => notAvailable('validateWorld'),

  // Build and simulation — not available in static mode
  buildWorld: () => notAvailable('buildWorld'),
  getBuildGrid: async (): Promise<BuildGrid> => notAvailable('getBuildGrid'),
  startBuildJob: async (): Promise<BuildJob> => notAvailable('startBuildJob'),
  getBuildJob: async (): Promise<BuildJob> => notAvailable('getBuildJob'),
  getClimateTrialInputs: async (world: string, planet: string, branch: string | null) =>
    (await browserEbmSource(world, planet, branch)).forcing,
  startClimateTrial: async (world: string, planet: string, branch: string | null,
    forcing: Partial<ClimateTrialForcing>, signal: AbortSignal) => {
    const source = await browserEbmSource(world, planet, branch, signal)
    const { startBrowserEbm } = await import('../playground/browserEbm')
    return startBrowserEbm({ config: source.config, cells: source.cells, mesh: source.mesh, forcing,
      runtime: new URL(`${import.meta.env.BASE_URL}${__PLAYGROUND_RUNTIME_PATH__}`, document.baseURI).href,
      solver: new URL(`${DATA_BASE}/climate_solver.zip`, document.baseURI).href }, signal)
  },
  getClimateTrial: async (id: string) => (await import('../playground/browserEbm')).getBrowserEbm(id),
  getClimateTrialProducts: async (id: string) => (await import('../playground/browserEbm')).getBrowserEbmProducts(id),
  saveClimateTrial: async (): Promise<never> => notAvailable('saveClimateTrial'),
  listSavedClimateTrials: async (): Promise<[]> => [],
  getSavedClimateTrial: async (): Promise<never> => notAvailable('getSavedClimateTrial'),
  deleteSavedClimateTrial: async (): Promise<never> => notAvailable('deleteSavedClimateTrial'),
  getPackElevation: async (): Promise<Blob> => notAvailable('getPackElevation'),
  getRegionDevice: async () => notAvailable('getRegionDevice'),
  planRegionRefinement: async (_source: RegionRefinementSource) => notAvailable('planRegionRefinement'),
  startRegionRefinement: async (_source: RegionRefinementSource) => notAvailable('startRegionRefinement'),
  getRegionRefinement: async () => notAvailable('getRegionRefinement'),
  cancelRegionRefinement: async () => notAvailable('cancelRegionRefinement'),

  // Data access (branch-aware: fetches from branches/{branch}/ when branch is set)
  getStellarSystem: (name: string, branch?: string | null) =>
    branch
      ? fetchStaticJson<any>(`/worlds/${name}/branches/${branch}/stellar.json`)
      : fetchStaticJson<any>(`/worlds/${name}/stellar.json`),

  getHabitableZones: (name: string, branch?: string | null) =>
    branch
      ? fetchStaticJson<any>(`/worlds/${name}/branches/${branch}/habitable_zones.json`)
      : fetchStaticJson<any>(`/worlds/${name}/habitable_zones.json`),

  getPlanets: (name: string, branch?: string | null) =>
    branch
      ? fetchStaticJson<any[]>(`/worlds/${name}/branches/${branch}/planets.json`)
      : fetchStaticJson<any[]>(`/worlds/${name}/planets.json`),

  getSystemCatalog: (name: string, branch?: string | null) =>
    branch
      ? fetchStaticJson<SystemCatalog>(`/worlds/${name}/branches/${branch}/system_catalog.json`)
      : fetchStaticJson<SystemCatalog>(`/worlds/${name}/system_catalog.json`),

  // Branches
  listBranches: (name: string) =>
    fetchStaticJson<any[]>(`/worlds/${name}/branches.json`),


  // Legacy civilization documents (delegate to generic layer-documents)
  listCivilizationDocuments: (name: string, branch?: string | null) =>
    staticApi.listLayerDocuments(name, 'civilization', branch),

  getCivilizationDocument: (name: string, filename: string, branch?: string | null) =>
    staticApi.getLayerDocument(name, 'civilization', filename, branch),

  // ---- Layer documents (generalized for any layer) ----

  listLayerDocuments: async (name: string, layer: string, branch?: string | null) => {
    const jsonFile = `/${layer}_documents.json`
    const data = await fetchBranchAwareJson<any>(name, branch, jsonFile, jsonFile)
    if (!data) return [] as DocumentMeta[]
    return data.map((d: Record<string, unknown>) => ({
      filename: d.filename as string,
      title: d.title as string,
      type: d.type as string,
      period: d.period as string | undefined,
      tags: (d.tags as string[]) || [],
      // Status-aware grouping (LayerDocuments designGroups) reads this;
      // older exports lack the field → undefined → treated as active.
      status: (d.status as string) || undefined,
    })) as DocumentMeta[]
  },

  getLayerDocument: async (name: string, layer: string, filename: string, branch?: string | null) => {
    const jsonFile = `/${layer}_documents.json`
    const data = await fetchBranchAwareJson<any[]>(name, branch, jsonFile, jsonFile)
    if (!data) throw new Error(`No ${layer} documents in static data`)
    const doc = data.find((d: any) => d.filename === filename)
    if (!doc) throw new Error(`Document '${filename}' not found`)
    return {
      filename: doc.filename,
      title: doc.title,
      frontmatter: doc.frontmatter || {},
      content: doc.content,
      // Older exports lack the field; treat a missing flag as rendered.
      rendered: doc.rendered !== false,
    }
  },

  // ---- Design documents (non-layer, cross-cutting design notes) ----

  listDesignDocuments: async (name: string, branch?: string | null) => {
    const data = await fetchBranchAwareJson<any>(
      name, branch, '/design-notes_documents.json', '/design-notes_documents.json',
    )
    if (!data) return [] as DocumentMeta[]
    return data.map((d: Record<string, unknown>) => ({
      filename: d.filename as string,
      title: d.title as string,
      type: d.type as string,
      period: d.period as string | undefined,
      tags: (d.tags as string[]) || [],
      // Status-aware grouping (LayerDocuments designGroups) reads this;
      // older exports lack the field → undefined → treated as active.
      status: (d.status as string) || undefined,
    })) as DocumentMeta[]
  },

  getDesignDocument: async (name: string, filename: string, branch?: string | null) => {
    const data = await fetchBranchAwareJson<any[]>(
      name, branch, '/design-notes_documents.json', '/design-notes_documents.json',
    )
    if (!data) throw new Error('No design documents in static data')
    const doc = data.find((d: any) => d.filename === filename)
    if (!doc) throw new Error(`Document '${filename}' not found`)
    return {
      filename: doc.filename,
      title: doc.title,
      frontmatter: doc.frontmatter || {},
      content: doc.content,
      // Older exports lack the field; treat a missing flag as rendered.
      rendered: doc.rendered !== false,
    }
  },

  getClimate: (name: string, branch?: string | null) =>
    branch
      ? fetchStaticJson<any>(`/worlds/${name}/branches/${branch}/climate.json`)
      : fetchStaticJson<any>(`/worlds/${name}/climate.json`),

  getEcology: (name: string, branch?: string | null) =>
    branch
      ? fetchStaticJson<any>(`/worlds/${name}/branches/${branch}/ecology.json`)
      : fetchStaticJson<any>(`/worlds/${name}/ecology.json`),

  // ---- Map read operations (branch-aware with root fallback) ----

  listMapPlanets: async (name: string, branch?: string | null): Promise<string[]> => {
    // The exported index includes inherited planets in the API's branch-first order.
    const result = await fetchBranchAwareJson<string[]>(
      name,
      branch,
      '/maps/maps.json',
      '/maps/maps.json',
    )
    return result ?? []
  },

  getMapMeta: async (name: string, planetId: string, branch?: string | null) => {
    const result = await fetchBranchAwareJson<MapResultMetadata>(
      name,
      branch,
      `/maps/${planetId}/meta.json`,
      `/maps/${planetId}/meta.json`,
    )
    if (result === null) throw new Error(`No static map metadata for ${planetId}`)
    return result
  },

  getElevationBlob: async (name: string, planetId: string, branch?: string | null) => {
    const result = await fetchBranchAwareBlob(
      name,
      branch,
      `/maps/${planetId}/elevation.png`,
      `/maps/${planetId}/elevation.png`,
    )
    if (result === null) throw new Error(`No static elevation data for ${planetId}`)
    return result
  },

  getVoronoi: async (name: string, planetId: string, branch?: string | null) => {
    // Prefer the CVT mesh (current format, same as backend API)
    const cvtData = await fetchBranchAwareMesh(name, branch, planetId)
    if (cvtData !== null) {
      // Convert CVT mesh cells to VoronoiNetwork format
      return {
        seed: cvtData.seed ?? 0,
        num_cells: cvtData.num_cells ?? 0,
        relaxation_iterations: cvtData.lloyd_iterations ?? 0,
        cells: (cvtData.cells || []).map((c: any) => ({
          id: c.id,
          lon: c.lon,
          lat: c.lat,
          x: c.x,
          y: c.y,
          z: c.z,
          elevation: c.elevation,
          moisture: c.moisture ?? 0,
          neighbors: c.neighbors ?? [],
          plate_id: c.plate_id ?? null,
          biome: c.biome ?? null,
          province_id: c.province_id ?? null,
          area_km2: c.area_km2,
          crust_type: c.crust_type,
          distance_to_boundary_km: c.distance_to_boundary_km,
          boundary_type: c.boundary_type ?? null,
          convergence_rate_cm_yr: c.convergence_rate_cm_yr,
          relief_std_m: c.relief_std_m ?? null,
          peak_elevation_m: c.peak_elevation_m ?? null,
          convergent_duration_my: c.convergent_duration_my ?? null,
          convergent_run_km: c.convergent_run_km ?? null,
          cumulative_convergence_km: c.cumulative_convergence_km ?? null,
          cumulative_divergence_km: c.cumulative_divergence_km ?? null,
          trench_axis_elevation_m: c.trench_axis_elevation_m ?? null,
          island_count: c.island_count ?? null,
          island_peak_m: c.island_peak_m ?? null,
          island_area_frac: c.island_area_frac ?? null,
          is_lake: c.is_lake,
          water_class: c.water_class,
        })),
      }
    }

    // Fall back to legacy voronoi.json (old static exports only)
    const legacy = await fetchBranchAwareJson<any>(
      name,
      branch,
      `/maps/${planetId}/voronoi.json`,
      `/maps/${planetId}/voronoi.json`,
    )
    if (legacy !== null) return legacy

    throw new Error(`No static voronoi data for ${planetId}`)
  },

  getCvtMesh: async (name: string, planetId: string, branch?: string | null) => {
    const { mark } = await import('../utils/perf')
    mark('mesh-fetch-start')
    try {
      const result = await fetchBranchAwareMesh(name, branch, planetId)
      if (result === null) throw new Error(`No static CVT mesh data for ${planetId}`)
      return result
    } finally {
      mark('mesh-fetch-end')
    }
  },

  getMonthlyClimate: async (
    name: string,
    planetId: string,
    branch?: string | null,
  ): Promise<MonthlyClimateData | null> => {
    const blob = await fetchBranchAwareBlob(
      name,
      branch,
      `/maps/${planetId}/climate_monthly.msgpack`,
      `/maps/${planetId}/climate_monthly.msgpack`,
    )
    if (blob === null) return null
    return decodeMonthlyClimate(await blob.arrayBuffer())
  },

  getYearlyClimate: async (
    name: string,
    planetId: string,
    branch?: string | null,
  ): Promise<YearlyClimateData | null> => {
    const blob = await fetchBranchAwareBlob(
      name,
      branch,
      `/maps/${planetId}/climate_yearly.msgpack`,
      `/maps/${planetId}/climate_yearly.msgpack`,
    )
    if (blob === null) return null
    return decodeYearlyClimate(await blob.arrayBuffer())
  },

  getPlates: async (name: string, planetId: string, branch?: string | null) => {
    const result = await fetchBranchAwareJson<{ plates?: any[] }>(
      name,
      branch,
      `/maps/${planetId}/plates.json`,
      `/maps/${planetId}/plates.json`,
    )
    return result?.plates ?? []
  },

  // ---- CivMap read operations ----

  getCivBoundaries: (name: string, level: string) => fetchStaticJson<GeoBoundaryCollection | null>(
    `/worlds/${name}/civmap/${level}.geojson`, () => null,
  ),

  getCivMapping: async (name: string): Promise<Record<string, string[]>> => {
    try {
      return await fetchStaticJson(`/worlds/${name}/civmap/mapping.json`)
    } catch {
      return {}
    }
  },

  getCivTerritory: async (name: string, branch?: string | null): Promise<CivTerritory> => {
    const root = `/worlds/${name}`
    const branchTerritory = branch
      ? await fetchStaticJson<CivTerritory | null>(`${root}/branches/${branch}/civ_territory.json`, () => null)
      : null
    const result = branchTerritory ?? await fetchStaticJson<CivTerritory | null>(`${root}/civ_territory.json`, () => null)
    return result ?? { countries: [], snapshots: [], active_snapshot: null, assignments: {} }
  },

  getCivAvailableLevels: async (name: string): Promise<string[]> => {
    const meta = await fetchStaticJson<{ levels?: Record<string, unknown> }>(
      `/worlds/${name}/civmap/metadata.json`, () => ({}),
    )
    return Object.keys(meta.levels ?? {})
  },

  // CivMap write operations — not available in static mode
  saveCivTerritory: () => notAvailable('saveCivTerritory'),
  upsertCivCountry: () => notAvailable('upsertCivCountry'),
  deleteCivCountry: () => notAvailable('deleteCivCountry'),
  createCivSnapshot: () => notAvailable('createCivSnapshot'),
  updateCivSnapshot: () => notAvailable('updateCivSnapshot'),
  deleteCivSnapshot: () => notAvailable('deleteCivSnapshot'),
  patchCivAssignments: () => notAvailable('patchCivAssignments'),
}

