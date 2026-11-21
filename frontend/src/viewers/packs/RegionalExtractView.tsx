import { useMemo, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api } from '../../api/client'
import { isStaticMode } from '../../api/mode'
import RegionElevationDownload from '../../components/map/RegionElevationDownload'
import SaveProjectResult from '../../components/projects/SaveProjectResult'
import { importedRasterSpacingKm } from '../map/elevationSource'
import RegionRefinementPanel from './RegionRefinementPanel'
import TerrainCompute, { type BrowserTerrainResult } from './TerrainCompute'
import { regionPackWindow, type RegionWindow } from '../map/regionWindow'
import type { LonLat } from '../map/utils/mapCoords'
import PackMap from './PackMap'
import PackStatusBar from './PackStatusBar'
import RasterPointInspector from './RasterPointInspector'
import RegionMapWorkspace from './RegionMapWorkspace'
import RegionLayerPanel from './RegionLayerPanel'
import { regionContextWindow } from './packCoords'
import { useRegionElevation, type ElevationInput } from './useRegionElevation'
import { useElevationPreview } from './useElevationPreview'
import type { ElevationFormat } from './elevationRaster'

interface Props {
  world: string
  planet: string
  branch: string | null
  radiusKm: number
  selection: RegionWindow
  globalReturn: string
  regionParams: URLSearchParams
  sourceControl?: ReactNode
}

export default function RegionalExtractView({ world, planet, branch, radiusKm, selection, globalReturn, regionParams, sourceControl }: Props) {
  const { t } = useTranslation('map')
  const { lat, lon, spanKm } = selection
  const window = useMemo(() => regionPackWindow({ lat, lon, spanKm }, radiusKm), [lat, lon, spanKm, radiusKm])
  const contextWindow = useMemo(() => regionContextWindow(window), [window])
  const meta = useQuery({ queryKey: ['mapMeta', world, planet, branch], queryFn: () => api.getMapMeta(world, planet, branch), retry: false })
  const elevation = useQuery({ queryKey: ['elevationBlob', world, planet, branch], queryFn: () => api.getElevationBlob(world, planet, branch), retry: false })
  const min = meta.data?.elevation_min_m ?? 0
  const max = meta.data?.elevation_max_m ?? 0
  const sea = meta.data?.sea_level_m ?? 0
  const pixelCentres = Boolean(meta.data?.elevation_import)
  const decoded = useMemo<ElevationInput | null>(() => meta.data && elevation.data
    ? { kind: 'global', blob: elevation.data, min, max, window, pixelCentres, context: contextWindow } : null,
    [meta.data, elevation.data, min, max, window, pixelCentres, contextWindow])
  const height = useRegionElevation(decoded)
  const preview = height.ready?.kind === 'preview' ? height.ready : null
  const [result, setResult] = useState<BrowserTerrainResult | null>(null)
  const refined = result?.raster
  const [showRefined, setShowRefined] = useState(false)
  const [graticule, setGraticule] = useState(0)
  const displayed = (showRefined ? refined : null) ?? preview?.raster ?? null
  const base = useElevationPreview(displayed, min, max, sea)
  const surround = useElevationPreview(height.context, min, max, sea)
  const context = useMemo(() => contextWindow && surround ? { window: contextWindow, url: surround.url } : null,
    [contextWindow, surround])
  const stepKm = Math.PI * radiusKm / Math.max(1, (preview?.sourceHeight ?? 1) - (pixelCentres ? 0 : 1))
  const nativeEstimateKm = meta.data && preview
    ? importedRasterSpacingKm(meta.data, preview.sourceWidth, preview.sourceHeight, radiusKm) : null
  const defaultSize = Math.max(1, Math.min(2048, Math.floor(spanKm / stepKm)))
  const [hover, setHover] = useState<LonLat | null>(null)
  const [pin, setPin] = useState<LonLat | null>(null)
  const missing = meta.isError || elevation.isError || (elevation.isSuccess && !elevation.data)
  const downloadRefined = (format: ElevationFormat) => {
    if (!result) return
    height.download(`${world}-${planet}-${lat}_${lon}-${result.recipe.method}`, null, format, {
      world, planet, branch, source: 'browser_terrain_diffusion', conditioning: 'elevation_only', seed: result.recipe.seed,
      model_manifest_sha256: result.manifestSha256,
      processing_mode: result.recipe.method, processing_recommendation: result.recommendation, source_native_spacing_km: result.nativeSpacingKm,
      decoder_residual_gain: result.recipe.residualGain,
      ...(result.recipe.method === 'blend' && { preserve_wavelength_km: result.recipe.preserveKm }),
      projection: window.projection, center_lat: lat, center_lon: lon, radius_km: radiusKm,
      extent_km: { x: spanKm, y: spanKm }, sea_level_m: sea, pixel_size_m: spanKm * 1000 / result.raster.width,
    }, result.raster)
  }

  return (
      <RegionMapWorkspace backTo={globalReturn} backLabel={t('regionWindow.back')}
        subtitle={t('regionWindow.summary', { lat, lon, spanKm })}
        sourceControl={sourceControl}
        status={<PackStatusBar hover={hover} window={window} />}
        inspector={<RasterPointInspector point={pin} window={window} original={preview?.raster} refined={refined} />}
        onClearPoint={pin ? () => setPin(null) : undefined}
        layers={<RegionLayerPanel notice="elevationOnly" compare={refined ? { original: !showRefined, onChange: original => setShowRefined(!original) } : undefined}
          graticule={{ opacity: graticule, onChange: setGraticule }} />}
        regionTools={<>
          <div className="space-y-1">
            <p className="font-medium text-gray-200">{t(showRefined ? 'packs.refinement.adopted' : 'packs.export.global')}</p>
            <p className="lg:hidden">{t('regionWindow.summary', { lat, lon, spanKm })}</p>
            <p>{t(showRefined ? 'packs.compute.refinedHint' : 'packs.export.globalHint')}</p>
          </div>
          <TerrainCompute browser={{ raster: preview?.raster ?? null, spanKm, seaLevel: sea,
            nativeEstimateKm,
            sourceRowSpacingKm: preview && preview.sourceHeight > 1 ? stepKm : null, onResult: (result) => {
            setResult(result)
            setShowRefined(true)
          } }}>{!isStaticMode() && <RegionRefinementPanel source={{ kind: 'world', world, planet, branch, lat, lon, span_km: spanKm }}
            globalReturn={globalReturn} resultUrl={(pack) => {
              const params = new URLSearchParams(regionParams)
              params.set('pack', pack)
              return `/packs?${params}`
            }} />}</TerrainCompute>
          {result && refined && <div className="space-y-2 rounded border border-space-border p-2">
            <p role="status">{t('packs.compute.resultSize', { width: refined.width, height: refined.height,
              metres: Math.round(spanKm * 1000 / refined.width) })}</p>
            <p>{t('packs.compute.resultMethod', { method: t(`packs.compute.method.${result.recipe.method}`) })}</p>
            <RegionElevationDownload fixedSize defaultSize={null} sourceStepKm={spanKm / refined.width} extentKm={spanKm}
              downloadLabel={t('packs.compute.download')} exporting={height.exporting} failed={height.failed}
              onDownload={(_, format) => downloadRefined(format)} />
            {isStaticMode() && preview && <SaveProjectResult result={result} target={{ worldId: world, planet, branch,
              sourceName: `${world} · ${planet} · ${lat}°, ${lon}° · ${spanKm} km`, raster: preview.raster,
              frame: { window, min, max, sea, sourceStepKm: stepKm } }} />}
          </div>}
          {preview && <details className="rounded border border-space-border p-2">
            <summary className="cursor-pointer font-medium text-neon-cyan">{t('packs.compute.exportOriginal')}</summary>
            <div className="mt-2">
              <RegionElevationDownload defaultSize={defaultSize} sourceStepKm={stepKm} extentKm={spanKm}
                exporting={height.exporting} failed={height.failed} onDownload={(size, format) => height.download(
                  `${world}-${planet}-${lat}_${lon}-${size}`, size, format, {
                    world, planet, branch, source: 'global_elevation', projection: window.projection,
                    center_lat: lat, center_lon: lon, radius_km: radiusKm, extent_km: { x: spanKm, y: spanKm },
                    sea_level_m: sea, source_width: preview.sourceWidth, source_height: preview.sourceHeight,
                    sampling: 'bilinear', source_row_spacing_km: stepKm,
                  })} />
            </div>
          </details>}
        </>}>
        {preview ? <PackMap window={window} base={base} loading={!base} context={context} rivers={null} graticuleOpacity={graticule} pin={pin}
          onHover={setHover} onProbe={setPin} /> : (
          <div className="absolute inset-0 grid place-content-center gap-2 p-4 text-center text-sm text-gray-400">
            <p role={missing || height.failed ? 'alert' : 'status'}>{t(missing ? 'packs.export.missing' : height.failed ? 'packs.export.previewFailed' : 'status.loading')}</p>
            {height.failed && <button type="button" className="min-h-11 text-neon-cyan hover:underline" onClick={height.retry}>{t('packs.export.retry')}</button>}
          </div>
        )}
      </RegionMapWorkspace>
  )
}
