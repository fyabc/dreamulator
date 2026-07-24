/**
 * Static data client — reads pre-exported JSON from /data/.
 *
 * Used for GitHub Pages deployment where no backend is available.
 * Only supports read operations; write operations throw.
 */

// Vite replaces BASE_URL at build time with the configured base path
// e.g. '/' for local preview, '/dreamulator/' for GitHub Pages
const DATA_BASE = `${import.meta.env.BASE_URL}data`

async function fetchStaticJson<T>(path: string): Promise<T> {
  const response = await fetch(`${DATA_BASE}${path}`)
  if (!response.ok) {
    throw new Error(`Static data not found: ${path} (HTTP ${response.status})`)
  }
  return response.json() as Promise<T>
}

async function fetchStaticBlob(path: string): Promise<Blob> {
  const response = await fetch(`${DATA_BASE}${path}`)
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

function notAvailable(operation: string): never {
  throw new Error(`${operation} is not available in static mode`)
}

export interface StaticNarrateUsage {
  input_tokens: number
  output_tokens: number
  total_tokens: number
}

export const staticApi = {
  // World operations (read-only)
  listWorlds: () => fetchStaticJson<string[]>('/worlds.json'),

  getWorld: (name: string) => fetchStaticJson<any>(`/worlds/${name}/world.json`),

  // Write operations — not available in static mode
  createWorld: () => notAvailable('createWorld'),
  deleteWorld: () => notAvailable('deleteWorld'),
  validateWorld: () => notAvailable('validateWorld'),

  // Build and simulation — not available in static mode
  buildWorld: () => notAvailable('buildWorld'),

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
    if (!data) return [] as any[]
    return data.map((d: any) => ({
      filename: d.filename,
      title: d.title,
      type: d.type,
      period: d.period,
      tags: d.tags || [],
    }))
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
    }
  },

  // ---- Design documents (non-layer, cross-cutting design notes) ----

  listDesignDocuments: async (name: string, branch?: string | null) => {
    const data = await fetchBranchAwareJson<any>(
      name, branch, '/design-notes_documents.json', '/design-notes_documents.json',
    )
    if (!data) return [] as any[]
    return data.map((d: any) => ({
      filename: d.filename,
      title: d.title,
      type: d.type,
      period: d.period,
      tags: d.tags || [],
    }))
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
    const result = await fetchBranchAwareJson<string[]>(
      name,
      branch,
      '/maps/maps.json',
      '/maps/maps.json',
    )
    return result ?? []
  },

  getMapMeta: async (name: string, planetId: string, branch?: string | null) => {
    const result = await fetchBranchAwareJson<any>(
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
    // Try voronoi.json first
    const result = await fetchBranchAwareJson<any>(
      name,
      branch,
      `/maps/${planetId}/voronoi.json`,
      `/maps/${planetId}/voronoi.json`,
    )
    if (result !== null) return result

    // Fall back to cvt_mesh.json (same as backend API)
    const cvtData = await fetchBranchAwareJson<any>(
      name,
      branch,
      `/maps/${planetId}/cvt_mesh.json`,
      `/maps/${planetId}/cvt_mesh.json`,
    )
    if (cvtData === null) throw new Error(`No static voronoi data for ${planetId}`)

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
      })),
    }
  },

  getCvtMesh: async (name: string, planetId: string, branch?: string | null) => {
    const result = await fetchBranchAwareJson<any>(
      name,
      branch,
      `/maps/${planetId}/cvt_mesh.json`,
      `/maps/${planetId}/cvt_mesh.json`,
    )
    if (result === null) throw new Error(`No static CVT mesh data for ${planetId}`)
    return result
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

  getFeatures: async (name: string, planetId: string, branch?: string | null) => {
    const result = await fetchBranchAwareJson<{ features?: any[] }>(
      name,
      branch,
      `/maps/${planetId}/features.json`,
      `/maps/${planetId}/features.json`,
    )
    return result?.features ?? []
  },

  // ---- CivMap read operations ----

  getCivBoundaries: async (name: string, level: string): Promise<any> => {
    try {
      return await fetchStaticJson(`/worlds/${name}/civmap/${level}.geojson`)
    } catch {
      return null
    }
  },

  getCivMapping: async (name: string): Promise<Record<string, string[]>> => {
    try {
      return await fetchStaticJson(`/worlds/${name}/civmap/mapping.json`)
    } catch {
      return {}
    }
  },

  getCivTerritory: async (name: string, branch?: string | null) => {
    const result = await fetchBranchAwareJson<any>(
      name,
      branch,
      '/civ_territory.json',
      '/civ_territory.json',
    )
    return result ?? { countries: [], snapshots: [], active_snapshot: null, assignments: {} }
  },

  getCivAvailableLevels: async (name: string): Promise<string[]> => {
    // Check which GeoJSON files exist by trying to fetch metadata
    try {
      const meta = await fetchStaticJson<any>(`/worlds/${name}/civmap/metadata.json`)
      return Object.keys(meta.levels || {})
    } catch {
      return []
    }
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

