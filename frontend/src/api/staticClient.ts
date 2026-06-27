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

  getCivilizations: (name: string, branch?: string | null) =>
    branch
      ? fetchStaticJson<any>(`/worlds/${name}/branches/${branch}/civilizations.json`)
      : fetchStaticJson<any>(`/worlds/${name}/civilizations.json`),

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
    const result = await fetchBranchAwareJson<any>(
      name,
      branch,
      `/maps/${planetId}/voronoi.json`,
      `/maps/${planetId}/voronoi.json`,
    )
    if (result === null) throw new Error(`No static voronoi data for ${planetId}`)
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
}
