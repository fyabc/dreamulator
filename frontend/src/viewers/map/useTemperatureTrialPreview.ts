import { useCallback, useEffect, useMemo, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { DataTexture, LinearFilter, NearestFilter, RepeatWrapping, SRGBColorSpace } from 'three'
import { GRID_H, GRID_W } from '../../playground/temperatureDraft'
import { temperaturePreviewPixels, type TemperaturePreview } from '../../playground/temperaturePreview'
import type { LayerState } from '../../components/map/MapLayerPanel'
import type { ClimateTrialResult } from '../../api/climateTrials'
import { climateRasterPixels } from './climateDownscale'
import { temperatureColor } from './utils/colorScales'

export type MapMode = 'official' | 'trial'

/** URL parameter holding the map's result source (official build or development result). */
export const RESULT_MODE_PARAM = 'result'

/**
 * Resolve the map mode from the URL. Without an explicit choice the map keeps
 * the previous default: a saved climate result opens as a development result,
 * everything else opens as the official build.
 */
export function resolveMapMode(param: string | null, saved: string | null | undefined): MapMode {
  if (param === 'development') return 'trial'
  if (param === 'official') return 'official'
  return saved ? 'trial' : 'official'
}

/** URL value for a mode (internal trial = development in the UI). */
export function resultModeValue(mode: MapMode): 'official' | 'development' {
  return mode === 'trial' ? 'development' : 'official'
}
export type ClimateTrialTime = { monthly: boolean; month: number }
export type EbmMapView = {
  result: ClimateTrialResult
  layers: LayerState
  setLayers: (state: LayerState) => void
  time: ClimateTrialTime
  setTime: (time: ClimateTrialTime) => void
}

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
    const pixels = downscale ? climateRasterPixels({ width: GRID_W, height: GRID_H, values: Float32Array.from(field) }, width, height, temperatureColor)
      : temperaturePreviewPixels(field)
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
  ebm: EbmMapView | null
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
