import { useCallback, useEffect, useMemo, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { DataTexture, LinearFilter, NearestFilter, RepeatWrapping, SRGBColorSpace } from 'three'
import { GRID_H, GRID_W } from '../../playground/temperatureDraft'
import { temperaturePreviewPixels, type TemperaturePreview } from '../../playground/temperaturePreview'
import type { LayerState } from '../../components/map/MapLayerPanel'
import { climateRasterPixels, climateRasterSurface } from './climateDownscale'
import { temperatureColor } from './utils/colorScales'

export type MapMode = 'official' | 'trial'

export function useTemperatureTrialPreview(scope: string | null, mode: MapMode, downscale: boolean) {
  const [reported, setReported] = useState<{ scope: string; preview: TemperaturePreview } | null>(null)

  const report = useCallback((preview: TemperaturePreview | null) => {
    if (scope) setReported(preview ? { scope, preview } : null)
  }, [scope])
  const available = reported?.scope === scope ? reported.preview : null
  const preview = mode === 'trial' ? available : null
  const field = available?.field
  const terrain = available?.terrain
  const texture = useMemo(() => {
    if (mode !== 'trial' || !field || !terrain) return null
    const width = downscale ? GRID_W * 4 : GRID_W
    const height = downscale ? GRID_H * 4 : GRID_H
    const surface = climateRasterSurface({ elevation: terrain.elevation, width: GRID_W, height: GRID_H,
      minM: terrain.params.elevMinM, maxM: terrain.params.elevMaxM, seaLevelM: terrain.params.seaLevelM }, width, height)
    const values = downscale ? Float32Array.from(field, (value, index) =>
      Number.isFinite(surface((index % GRID_W) * 4, Math.floor(index / GRID_W) * 4)) ? value : NaN) : null
    const pixels = values ? climateRasterPixels({ width: GRID_W, height: GRID_H, values }, width, height, temperatureColor, surface)
      : temperaturePreviewPixels(field, terrain)
    const result = new DataTexture(pixels as unknown as BufferSource, width, height)
    result.wrapS = RepeatWrapping
    result.minFilter = LinearFilter
    result.magFilter = downscale ? LinearFilter : NearestFilter
    result.colorSpace = SRGBColorSpace
    result.needsUpdate = true
    return result
  }, [field, terrain, downscale, mode])
  useEffect(() => () => texture?.dispose(), [texture])

  return { available, preview, texture: mode === 'trial' ? texture : null, report }
}

export type MapTemperatureTrialSession = ReturnType<typeof useTemperatureTrialPreview> & {
  open: boolean
  mode: MapMode
  layerState: LayerState
  setLayerState: (state: LayerState) => void
  selectMode: (mode: MapMode) => void
  openPanel: () => void
  closePanel: () => void
  attachPanel: (slot: HTMLDivElement | null) => void
  replaceElevation: () => void
}

export function useMapTemperatureTrial() {
  return useOutletContext<MapTemperatureTrialSession>()
}
