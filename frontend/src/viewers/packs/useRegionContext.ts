import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'
import type { PackWindow } from './packCoords'
import { regionContextWindow } from './packCoords'
import { useRegionElevation, type ElevationInput } from './useRegionElevation'
import { useElevationPreview } from './useElevationPreview'

export type RegionContext = { window: PackWindow; url: string; currentReference?: boolean }
export type WorldLocation = { world: string; planet: string; branch: string | null }

export function useRegionContext(location: WorldLocation | null, window: PackWindow | null,
  palette: { min: number; max: number; sea: number } | null) {
  const frame = useMemo(() => window && regionContextWindow(window), [window])
  const { world, planet, branch } = location ?? {}
  const enabled = Boolean(world && planet && frame && palette)
  const meta = useQuery({ queryKey: ['mapMeta', world, planet, branch], enabled,
    queryFn: () => api.getMapMeta(world!, planet!, branch), retry: false })
  const compatible = enabled && meta.data?.sea_level_m === palette?.sea ? meta.data : undefined
  const elevation = useQuery({ queryKey: ['elevationBlob', world, planet, branch], enabled: Boolean(compatible),
    queryFn: () => api.getElevationBlob(world!, planet!, branch), retry: false })
  const input = useMemo<ElevationInput | null>(() => compatible && elevation.data && frame ? {
    kind: 'context', blob: elevation.data, min: compatible.elevation_min_m, max: compatible.elevation_max_m,
    window: frame, pixelCentres: Boolean(compatible.elevation_import),
  } : null, [compatible, elevation.data, frame])
  const { context } = useRegionElevation(input)
  const image = useElevationPreview(context, palette?.min ?? 0, palette?.max ?? 0, palette?.sea ?? 0)
  return useMemo<RegionContext | null>(() => input && frame && image
    ? { window: frame, url: image.url, currentReference: true } : null, [input, frame, image])
}
