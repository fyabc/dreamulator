/** Observer candidates for the sky page's picker.
 *
 * Replicates the cheap rungs of the engine's spin-axis ladder so the select
 * only offers bodies the engine can observe from; the server stays the
 * authority (a slipped-through id gets a 422 with the engine's message).
 */

import type { SkyCatalog, SkyCatalogBody } from './types'

function observable(body: SkyCatalogBody): boolean {
  if (body.derived?.tidally_locked) return true
  if (body.derived?.spin_axis_ecliptic_longitude_deg != null) return true
  const tilt = body.physical?.axial_tilt_deg ?? 0
  return body.body_type === 'natural_satellite' && !tilt
}

export interface ObserverOption {
  id: string
  name: string
  isDefault: boolean
}

/** Observable bodies as picker options; the catalog target first. */
export function observerCandidates(catalog: SkyCatalog): ObserverOption[] {
  const target = catalog.target_body_id ?? null
  const bodies = (catalog.bodies ?? []).filter(observable)
  const options: ObserverOption[] = bodies.map((b) => ({
    id: b.id,
    name: b.name ?? b.id,
    isDefault: b.id === target,
  }))
  options.sort((a, b) => Number(b.isDefault) - Number(a.isDefault))
  return options
}
