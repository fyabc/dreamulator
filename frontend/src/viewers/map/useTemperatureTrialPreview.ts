import { useCallback, useEffect, useMemo, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { DataTexture, LinearFilter, RepeatWrapping } from 'three'
import { GRID_H, GRID_W } from '../../playground/temperatureDraft'
import { temperaturePreviewPixels, type TemperaturePreview } from '../../playground/temperaturePreview'
import type { LayerState } from '../../components/map/MapLayerPanel'

export type MapMode = 'official' | 'trial'

export function useTemperatureTrialPreview(scope: string | null, mode: MapMode) {
  const [reported, setReported] = useState<{ scope: string; preview: TemperaturePreview } | null>(null)

  const report = useCallback((preview: TemperaturePreview | null) => {
    if (scope) setReported(preview ? { scope, preview } : null)
  }, [scope])
  const available = reported?.scope === scope ? reported.preview : null
  const preview = mode === 'trial' ? available : null
  const field = available?.field
  const texture = useMemo(() => {
    if (!field) return null
    const result = new DataTexture(temperaturePreviewPixels(field), GRID_W, GRID_H)
    result.wrapS = RepeatWrapping
    result.minFilter = LinearFilter
    result.magFilter = LinearFilter
    result.needsUpdate = true
    return result
  }, [field])
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
