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

  // Data access
  getStellarSystem: (name: string) =>
    fetchStaticJson<any>(`/worlds/${name}/stellar.json`),

  getHabitableZones: (name: string) =>
    fetchStaticJson<any>(`/worlds/${name}/habitable_zones.json`),

  getPlanets: (name: string) =>
    fetchStaticJson<any[]>(`/worlds/${name}/planets.json`),

  // Branches
  listBranches: (name: string) =>
    fetchStaticJson<any[]>(`/worlds/${name}/branches.json`),

  // Civilization data
  getCivilizations: (name: string) =>
    fetchStaticJson<any>(`/worlds/${name}/civilizations.json`),
}
