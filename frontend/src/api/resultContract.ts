import type { MapMetadata } from '../viewers/map/types'

/** Shared metadata of API and static map results. Existing yearly blobs keep
 * their own declared format version until their next regeneration. */
export interface ResultMetadata {
  format_version: string
  time: {
    reference_year_days: number
    reference_month_days: number
  }
}

/** Normalized map fields plus retained generation provenance. */
export type MapResultMetadata = MapMetadata & ResultMetadata & Record<string, unknown>
