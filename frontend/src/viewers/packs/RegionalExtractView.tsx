import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api } from '../../api/client'
import { isStaticMode } from '../../api/mode'
import MapHelpLink from '../../components/map/MapHelpLink'
import RegionElevationDownload from '../../components/map/RegionElevationDownload'
import RegionRefinementPanel from './RegionRefinementPanel'
import { availableRegionPacks, matchingRegionPacks, regionPackWindow, type RegionWindow } from '../map/regionWindow'
import { generateAdaptiveTerrainScale } from '../map/utils/colorScales'
import type { LonLat } from '../map/utils/mapCoords'
import { lonLatToKm } from './packCoords'
import PackMap from './PackMap'
import PackStatusBar from './PackStatusBar'
import { useRegionElevation, type ElevationInput } from './useRegionElevation'
import type { ElevationRaster } from './elevationRaster'

interface Props {
  world: string
  planet: string
  branch: string | null
  radiusKm: number
  selection: RegionWindow
  globalReturn: string
  regionParams: URLSearchParams
}

function usePreviewImage(raster: ElevationRaster | null, min: number, max: number, sea: number) {
  const [base, setBase] = useState<{ url: string } | null>(null)
  useEffect(() => {
    setBase(null)
    if (!raster) return
    const canvas = document.createElement('canvas')
    canvas.width = raster.width
    canvas.height = raster.height
    const context = canvas.getContext('2d')
    if (!context) return
    const image = context.createImageData(raster.width, raster.height)
    const lut = generateAdaptiveTerrainScale(min, max, sea)
    const bins = lut.length / 4 - 1
    raster.values.forEach((height, index) => {
      const offset = 4 * Math.round(bins * Math.max(0, Math.min(1, (height - min) / (max - min || 1))))
      image.data[index * 4] = lut[offset]
      image.data[index * 4 + 1] = lut[offset + 1]
      image.data[index * 4 + 2] = lut[offset + 2]
      image.data[index * 4 + 3] = 255
    })
    context.putImageData(image, 0, 0)
    setBase({ url: canvas.toDataURL() })
  }, [raster, min, max, sea])
  return base
}

export default function RegionalExtractView({ world, planet, branch, radiusKm, selection, globalReturn, regionParams }: Props) {
  const { t } = useTranslation('map')
  const { lat, lon, spanKm } = selection
  const window = useMemo(() => regionPackWindow({ lat, lon, spanKm }, radiusKm), [lat, lon, spanKm, radiusKm])
  const meta = useQuery({ queryKey: ['mapMeta', world, planet, branch], queryFn: () => api.getMapMeta(world, planet, branch), retry: false })
  const elevation = useQuery({ queryKey: ['elevationBlob', world, planet, branch], queryFn: () => api.getElevationBlob(world, planet, branch), retry: false })
  const packs = useQuery({ queryKey: ['packs'], queryFn: api.listPacks, enabled: !isStaticMode(), retry: false })
  const matches = matchingRegionPacks(availableRegionPacks(packs.data ?? [], { world, planet, branch }, radiusKm), selection, radiusKm)
  const min = meta.data?.elevation_min_m ?? 0
  const max = meta.data?.elevation_max_m ?? 0
  const sea = meta.data?.sea_level_m ?? 0
  const decoded = useMemo<ElevationInput | null>(() => meta.data && elevation.data
    ? { kind: 'global', blob: elevation.data, min, max, window } : null, [meta.data, elevation.data, min, max, window])
  const height = useRegionElevation(decoded)
  const preview = height.ready?.kind === 'preview' ? height.ready : null
  const base = usePreviewImage(preview?.raster ?? null, min, max, sea)
  const stepKm = Math.PI * radiusKm / Math.max(1, (preview?.sourceHeight ?? 1) - 1)
  const defaultSize = Math.max(1, Math.min(2048, Math.floor(spanKm / stepKm)))
  const [hover, setHover] = useState<LonLat | null>(null)
  const [pin, setPin] = useState<LonLat | null>(null)
  const pinHeight = pin && preview ? (() => {
    const { x, y } = lonLatToKm(pin, window)
    const { width, height, values } = preview.raster
    if (Math.abs(x) > spanKm / 2 || Math.abs(y) > spanKm / 2) return null
    const col = Math.min(width - 1, Math.floor((x / spanKm + 0.5) * width))
    const row = Math.min(height - 1, Math.floor((0.5 - y / spanKm) * height))
    return values[row * width + col]
  })() : null
  const missing = meta.isError || elevation.isError || (elevation.isSuccess && !elevation.data)

  return (
    <div className="flex h-[calc(100dvh-56px)] flex-col md:h-screen">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-space-border bg-space-panel px-4 py-2">
        <Link className="text-xs text-neon-cyan hover:underline" to={globalReturn}>{t('regionWindow.back')}</Link>
        <h1 className="text-sm font-semibold text-gray-200">{t('packs.pickPrompt')}</h1>
        <span className="text-xs text-gray-400">{t('regionWindow.summary', { lat, lon, spanKm })}</span>
        <div className="ml-auto"><MapHelpLink section="packs" label={t('packs.help')} /></div>
      </div>
      <div className="flex min-h-0 flex-1 flex-col bg-space-bg md:flex-row">
        <aside className="max-h-[38dvh] shrink-0 space-y-3 overflow-auto border-b border-space-border bg-space-panel p-3 text-xs text-gray-400 md:max-h-none md:w-60 md:border-b-0 md:border-r">
          <div className="space-y-1">
            <p className="font-medium text-gray-200">{t('packs.export.global')}</p>
            <p>{t('packs.export.globalHint')}</p>
          </div>
          {matches.map(({ name }) => {
            const params = new URLSearchParams(regionParams)
            params.set('pack', name)
            return <Link key={name} className="block break-all text-neon-cyan hover:underline" to={`/packs?${params}`}
              state={{ regionReturn: globalReturn }}>{t('regionWindow.openPack', { name })}</Link>
          })}
          {!isStaticMode() && <RegionRefinementPanel source={{ kind: 'world', world, planet, branch, lat, lon, span_km: spanKm }}
            globalReturn={globalReturn} resultUrl={(pack) => {
              const params = new URLSearchParams(regionParams)
              params.set('pack', pack)
              return `/packs?${params}`
            }} />}
          {preview && <details className="rounded border border-space-border p-2">
            <summary className="cursor-pointer font-medium text-neon-cyan">{t('packs.export.title')}</summary>
            <div className="mt-2">
              <RegionElevationDownload defaultSize={defaultSize} sourceStepKm={stepKm} extentKm={spanKm}
                exporting={height.exporting} failed={height.failed} onDownload={(size, format) => height.download(
                  `${world}-${planet}-${lat}_${lon}-${size}`, size, format, {
                    world, planet, branch, source: 'global_elevation', projection: window.projection,
                    center_lat: lat, center_lon: lon, radius_km: radiusKm, extent_km: { x: spanKm, y: spanKm },
                    sea_level_m: sea, source_width: preview.sourceWidth, source_height: preview.sourceHeight,
                    sampling: 'bilinear',
                  })} />
            </div>
          </details>}
          {pinHeight !== null && <p>{t('packs.export.probe', { value: Math.round(pinHeight) })}</p>}
        </aside>
        <div className="relative isolate min-h-0 min-w-0 flex-1">
          {base ? <PackMap window={window} base={base} rivers={null} graticuleOn={false} pin={pin}
            onHover={setHover} onProbe={setPin} /> : (
            <div className="absolute inset-0 grid place-content-center gap-2 p-4 text-center text-sm text-gray-400">
              <p role="status">{t(missing ? 'packs.export.missing' : height.failed ? 'packs.export.previewFailed' : 'status.loading')}</p>
              {height.failed && <button type="button" className="text-neon-cyan hover:underline" onClick={height.retry}>{t('packs.export.retry')}</button>}
            </div>
          )}
        </div>
      </div>
      {base && <PackStatusBar hover={hover} window={window} />}
    </div>
  )
}
