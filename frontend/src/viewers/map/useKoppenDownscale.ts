import { useEffect, useMemo, useState } from 'react'
import type { MonthlyClimateData } from '../../api/monthlyClimate'
import type { ClimateRasterTerrain } from './climateDownscale'
import { hasKoppenMonths, type KoppenRasterInput } from './koppenDownscale'
import { makeTexture } from './layerBakes'
import type { CVTMesh } from './types'

export function useKoppenDownscale(active: boolean, enabled: boolean, monthly: MonthlyClimateData | null,
  mesh: CVTMesh | null, cellIds: Uint32Array | null, meshWidth: number, meshHeight: number,
  seaLevelM: number, native: ClimateRasterTerrain | null) {
  const input = useMemo<KoppenRasterInput | null>(() => {
    if (!active || !mesh || !cellIds || !monthly || !hasKoppenMonths(monthly, mesh.cells.length)) return null
    if (!mesh.cells.some(cell => cell.koppen_class && cell.koppen_class !== 'Ocean')) return null
    return {
      cells: mesh.cells.map(({ id, elevation, water_class, koppen_class }) => ({ id, elevation, water_class, koppen_class })),
      cellIds, meshWidth, meshHeight, width: Math.min(meshWidth, 2048), height: Math.min(meshHeight, 1024),
      seaLevelM, native, tMonthly: monthly.tMonthly, pMonthly: monthly.pMonthly,
    }
  }, [active, mesh, cellIds, monthly, meshWidth, meshHeight, seaLevelM, native])
  const [cachedResult, setResult] = useState<{ input: KoppenRasterInput; pixels: Uint8Array | null } | null>(null)
  const result = cachedResult?.input === input ? cachedResult : null

  useEffect(() => {
    if (!input || !enabled || result) return
    const worker = new Worker(new URL('./koppenDownscale.worker.ts', import.meta.url), { type: 'module' })
    const finish = (pixels: Uint8Array | null) => {
      worker.terminate()
      setResult({ input, pixels })
    }
    worker.onmessage = ({ data }: MessageEvent<Uint8Array | null>) => finish(data)
    worker.onerror = () => finish(null)
    worker.postMessage(input)
    return () => worker.terminate()
  }, [input, enabled, result])

  const texture = useMemo(() => result?.pixels
    ? makeTexture(result.pixels, result.input.width, result.input.height, { nearestMag: true }) : null, [result])
  useEffect(() => () => texture?.dispose(), [texture])

  return { texture: enabled ? texture : null, available: Boolean(input && (!result || result.pixels)),
    pending: Boolean(input && enabled && !result) }
}
