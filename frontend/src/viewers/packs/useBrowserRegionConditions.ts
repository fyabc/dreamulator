import { useMemo, useState } from 'react'
import type { RegionInspectorFields } from './ProbePanel'
import { regionConditionLayers, regionFields, type RegionPackBaseLayer } from './regionPackLayers'
import type { TerrainConditionSnapshot } from './terrainConditions'
import { useRegionFieldPreview } from './useRegionFieldPreview'

const gridChoice = ['grid'] as const
const selectGrid = () => undefined

export function useBrowserRegionConditions(snapshot: TerrainConditionSnapshot | undefined) {
  const [selected, setSelected] = useState<RegionPackBaseLayer>('mapElevation')
  const fields = useMemo(() => {
    const result: RegionInspectorFields = {}
    if (snapshot) {
      const { size } = snapshot
      for (const layer of regionConditionLayers) {
        const field = regionFields[layer].field
        const values = field === 'elevation_m' ? snapshot.elevation_m : snapshot.climate?.[field]
        if (values) result[layer] = { source: 'grid', raster: { width: size, height: size, values: Float32Array.from(values) },
          loading: false, failed: false }
      }
    }
    return result
  }, [snapshot])
  const available = useMemo(() => new Set<RegionPackBaseLayer>(['mapElevation', ...regionConditionLayers.filter(layer => fields[layer])]), [fields])
  const active = available.has(selected) ? selected : 'mapElevation'
  const layer = active === 'mapElevation' ? undefined : active
  const raster = layer && fields[layer]?.raster
  const preview = useRegionFieldPreview(raster, layer)
  const conditionSource = snapshot ? { source: 'grid' as const, choices: gridChoice, onChange: selectGrid } : undefined
  return { active, layer, raster, preview, fields, available, setSelected, conditionSource }
}
