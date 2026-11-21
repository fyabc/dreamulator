import { useCallback, useEffect, useMemo, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { DataTexture, LinearFilter, RepeatWrapping } from 'three'
import { GRID_H, GRID_W } from '../../playground/temperatureDraft'
import { temperaturePreviewPixels, type TemperaturePreview } from '../../playground/temperaturePreview'

export function useTemperatureTrialPreview(scope: string | null) {
  const [reported, setReported] = useState<{ scope: string; preview: TemperaturePreview } | null>(null)
  const [enabled, setEnabled] = useState(true)
  useEffect(() => {
    setReported(null)
    setEnabled(true)
  }, [scope])

  const report = useCallback((preview: TemperaturePreview | null) => {
    if (scope) setReported(preview ? { scope, preview } : null)
  }, [scope])
  const show = useCallback(() => setEnabled(true), [])
  const restore = useCallback(() => setEnabled(false), [])
  const preview = enabled && reported?.scope === scope ? reported.preview : null
  const field = preview?.field
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

  return { preview, texture, report, show, restore }
}

export type MapTemperatureTrialSession = ReturnType<typeof useTemperatureTrialPreview> & {
  open: boolean
  openPanel: () => void
  closePanel: () => void
  attachPanel: (slot: HTMLDivElement | null) => void
  replaceElevation: () => void
}

export function useMapTemperatureTrial() {
  return useOutletContext<MapTemperatureTrialSession>()
}
