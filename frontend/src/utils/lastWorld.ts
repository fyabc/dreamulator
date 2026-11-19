/**
 * The last world the author worked on, so the home page can offer to return
 * to it after a refresh.  Stored per browser; the world itself lives on the
 * server, so a stale entry (world deleted) is simply not shown.
 */

const KEY = 'dreamulator-last-world'

export interface LastWorld {
  world: string
  planetId: string | null
  branch: string | null
  /** In-app path to reopen, e.g. `/worlds/sample/map/planet_gaia`. */
  path: string
  /** ISO time of the last visit. */
  at: string
}

export function saveLastWorld(entry: Omit<LastWorld, 'at'>): void {
  try {
    localStorage.setItem(KEY, JSON.stringify({ ...entry, at: new Date().toISOString() }))
  } catch {
    // Storage unavailable (private mode, blocked site data): nothing to remember.
  }
}

export function loadLastWorld(): LastWorld | null {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return null
    const v = JSON.parse(raw) as Partial<LastWorld>
    if (typeof v.world !== 'string' || typeof v.path !== 'string' || !v.path.startsWith('/')) return null
    return {
      world: v.world,
      planetId: v.planetId ?? null,
      branch: v.branch ?? null,
      path: v.path,
      at: typeof v.at === 'string' ? v.at : '',
    }
  } catch {
    return null
  }
}
