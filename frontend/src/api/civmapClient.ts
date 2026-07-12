/**
 * CivMap API client — REST calls for the civilization map system.
 *
 * Follows the same pattern as the existing api/client.ts.
 */

import type {
  BoundaryLevel,
  CivCountry,
  CivSnapshot,
  CivTerritory,
  CountryProvinceMapping,
  GeoBoundaryCollection,
  TerritoryAssignment,
} from '../components/civmap/types'

const BASE = '/api/worlds'

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, init)
  if (!resp.ok) {
    const body = await resp.text().catch(() => '')
    throw new Error(`API ${resp.status}: ${body || resp.statusText}`)
  }
  return resp.json() as Promise<T>
}

function branchParam(branch: string | null | undefined): string {
  return branch ? `?branch=${encodeURIComponent(branch)}` : ''
}

// ---------------------------------------------------------------------------
// Reference GeoJSON (read-only)
// ---------------------------------------------------------------------------

export async function getBoundaries(
  world: string,
  level: BoundaryLevel,
  branch?: string | null,
  region?: string,
): Promise<GeoBoundaryCollection> {
  const r = region ? `/${encodeURIComponent(region)}` : ''
  return fetchJson(`${BASE}/${world}/civmap/boundaries/${level}${r}${branchParam(branch)}`)
}

export async function getAvailableLevels(
  world: string,
  branch?: string | null,
): Promise<string[]> {
  return fetchJson(`${BASE}/${world}/civmap/available-levels${branchParam(branch)}`)
}

export async function getCountryProvinceMapping(
  world: string,
  branch?: string | null,
): Promise<CountryProvinceMapping> {
  return fetchJson(`${BASE}/${world}/civmap/boundaries-mapping${branchParam(branch)}`)
}

// ---------------------------------------------------------------------------
// Territory data
// ---------------------------------------------------------------------------

export async function getTerritory(
  world: string,
  branch?: string | null,
): Promise<CivTerritory> {
  return fetchJson(`${BASE}/${world}/civmap/territory${branchParam(branch)}`)
}

export async function saveTerritory(
  world: string,
  territory: CivTerritory,
  branch?: string | null,
): Promise<void> {
  await fetchJson(`${BASE}/${world}/civmap/territory${branchParam(branch)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ territory }),
  })
}

// ---------------------------------------------------------------------------
// Country CRUD
// ---------------------------------------------------------------------------

export async function getCountries(
  world: string,
  branch?: string | null,
): Promise<CivCountry[]> {
  return fetchJson(`${BASE}/${world}/civmap/countries${branchParam(branch)}`)
}

export async function upsertCountry(
  world: string,
  country: CivCountry,
  branch?: string | null,
): Promise<CivTerritory> {
  const result = await fetchJson<{ ok: boolean; territory: CivTerritory }>(
    `${BASE}/${world}/civmap/countries${branchParam(branch)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ country }),
    },
  )
  return result.territory
}

export async function deleteCountry(
  world: string,
  countryId: string,
  branch?: string | null,
): Promise<CivTerritory> {
  const result = await fetchJson<{ ok: boolean; territory: CivTerritory }>(
    `${BASE}/${world}/civmap/countries/${encodeURIComponent(countryId)}${branchParam(branch)}`,
    { method: 'DELETE' },
  )
  return result.territory
}

// ---------------------------------------------------------------------------
// Snapshot CRUD
// ---------------------------------------------------------------------------

export async function getSnapshots(
  world: string,
  branch?: string | null,
): Promise<CivSnapshot[]> {
  return fetchJson(`${BASE}/${world}/civmap/snapshots${branchParam(branch)}`)
}

export async function createSnapshot(
  world: string,
  snapshot: CivSnapshot,
  branch?: string | null,
): Promise<CivTerritory> {
  const result = await fetchJson<{ ok: boolean; territory: CivTerritory }>(
    `${BASE}/${world}/civmap/snapshots${branchParam(branch)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ snapshot }),
    },
  )
  return result.territory
}

export async function updateSnapshot(
  world: string,
  snapshotId: string,
  snapshot: CivSnapshot,
  branch?: string | null,
): Promise<CivTerritory> {
  const result = await fetchJson<{ ok: boolean; territory: CivTerritory }>(
    `${BASE}/${world}/civmap/snapshots/${encodeURIComponent(snapshotId)}${branchParam(branch)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ snapshot }),
    },
  )
  return result.territory
}

export async function deleteSnapshot(
  world: string,
  snapshotId: string,
  branch?: string | null,
): Promise<CivTerritory> {
  const result = await fetchJson<{ ok: boolean; territory: CivTerritory }>(
    `${BASE}/${world}/civmap/snapshots/${encodeURIComponent(snapshotId)}${branchParam(branch)}`,
    { method: 'DELETE' },
  )
  return result.territory
}

// ---------------------------------------------------------------------------
// Assignment CRUD (within a snapshot)
// ---------------------------------------------------------------------------

export async function getAssignments(
  world: string,
  snapshotId: string,
  branch?: string | null,
): Promise<TerritoryAssignment[]> {
  return fetchJson(
    `${BASE}/${world}/civmap/snapshots/${encodeURIComponent(snapshotId)}/assignments${branchParam(branch)}`,
  )
}

export async function patchAssignments(
  world: string,
  snapshotId: string,
  updates: TerritoryAssignment[],
  branch?: string | null,
): Promise<CivTerritory> {
  const result = await fetchJson<{ ok: boolean; territory: CivTerritory }>(
    `${BASE}/${world}/civmap/snapshots/${encodeURIComponent(snapshotId)}/assignments${branchParam(branch)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ updates }),
    },
  )
  return result.territory
}
