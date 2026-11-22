import { useMemo, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api } from '../../api/client'
import { isStaticMode } from '../../api/mode'
import RegionElevationDownload from '../../components/map/RegionElevationDownload'
import SaveProjectResult from '../../components/projects/SaveProjectResult'
import { openProjectRaster } from '../../projects/elevationProject'
import { getProject, projectKey } from '../../projects/projectStore'
import { importedRasterSpacingKm } from '../map/elevationSource'
import RegionRefinementPanel from './RegionRefinementPanel'
import TerrainCompute, { type BrowserTerrainResult } from './TerrainCompute'
import { regionPackWindow, type RegionWindow } from '../map/regionWindow'
import type { LonLat } from '../map/utils/mapCoords'
import PackMap from './PackMap'
import PackStatusBar from './PackStatusBar'
import ProbePanel from './ProbePanel'
import RegionMapWorkspace from './RegionMapWorkspace'
import RegionLayerPanel from './RegionLayerPanel'
import { RegionDataSourceSelect } from './RegionResultSelector'
import { currentBrowserRefinement, matchingBrowserRegionResults } from './browserRegionResults'
import { regionContextWindow } from './packCoords'
import { useRegionElevation, type ElevationInput } from './useRegionElevation'
import { useElevationPreview } from './useElevationPreview'
import { useBrowserRegionConditions } from './useBrowserRegionConditions'
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
  const staticMode = isStaticMode()
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
  const [temporary, setTemporary] = useState<BrowserTerrainResult | null>(null)
  const [requestedSource, setRequestedSource] = useState('')
  const project = useQuery({ queryKey: projectKey(world), queryFn: () => getProject(world), enabled: staticMode, retry: false })
  const climateResult = staticMode && regionParams.get('climateResult') || undefined
  const savedResults = matchingBrowserRegionResults(project.data, { planet, branch, climateResult }, window)
  const saved = savedResults.find(({ layer }) => layer.id === requestedSource)
  const current = saved?.layer.id ?? (temporary && requestedSource === currentBrowserRefinement ? currentBrowserRefinement : '')
  const savedRasters = useQuery({ queryKey: ['region-saved-rasters', world, saved?.layer.id], enabled: Boolean(saved),
    retry: false, staleTime: Infinity, gcTime: 0,
    queryFn: async () => {
      const [original, raster] = await Promise.all([openProjectRaster(saved!.source), openProjectRaster(saved!.layer)])
      return { original, raster }
    } })
  const result = current === currentBrowserRefinement ? temporary : saved && savedRasters.data
    ? { ...saved.layer.settings, raster: savedRasters.data.raster } : null
  const conditions = useBrowserRegionConditions(result?.conditioning)
  const refined = result?.raster
  const [showRefined, setShowRefined] = useState(false)
  const [graticule, setGraticule] = useState(0)
  const original = saved ? savedRasters.data?.original : preview?.raster
  const showingResult = Boolean(current) && showRefined
  const displayed = (showingResult ? refined : original) ?? null
  const palette = saved?.source.frame ?? { min, max, sea }
  const base = useElevationPreview(displayed, palette.min, palette.max, palette.sea, true)
  const surround = useElevationPreview(palette.sea === sea ? height.context : null, palette.min, palette.max, sea)
  const currentReference = Boolean(saved)
  const context = useMemo(() => contextWindow && surround ? { window: contextWindow, url: surround.url, currentReference } : null,
    [contextWindow, surround, currentReference])
  const resultChoices = savedResults.map(({ layer }) => ({ name: layer.id, label: layer.name }))
  if (temporary) resultChoices.unshift({ name: currentBrowserRefinement, label: t('packs.results.currentBrowser') })
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
      world, planet, branch, source: 'browser_terrain_diffusion', seed: result.recipe.seed,
      ...(climateResult && { climate_result: climateResult }),
      ...(result.conditioning && { conditioning: result.conditioning.climate ? 'climate' : 'elevation_only', td_grid: result.conditioning }),
      model_manifest_sha256: result.manifestSha256,
      processing_mode: result.recipe.method, processing_recommendation: result.recommendation, source_native_spacing_km: result.nativeSpacingKm,
      decoder_residual_gain: result.recipe.residualGain,
      ...(result.recipe.method === 'blend' && { preserve_wavelength_km: result.recipe.preserveKm }),
      projection: window.projection, center_lat: lat, center_lon: lon, radius_km: radiusKm,
      extent_km: { x: spanKm, y: spanKm }, sea_level_m: palette.sea, pixel_size_m: spanKm * 1000 / result.raster.width,
    }, result.raster)
  }

  return (
      <RegionMapWorkspace backTo={globalReturn} backLabel={t('regionWindow.back')}
        subtitle={t('regionWindow.summary', { lat, lon, spanKm })}
        sourceControl={staticMode ? <RegionDataSourceSelect current={current} results={resultChoices} onChange={source => {
          setRequestedSource(source)
          setShowRefined(Boolean(source))
          conditions.setSelected('mapElevation')
        }} /> : sourceControl}
        status={<PackStatusBar hover={hover} window={window} />}
        inspector={<ProbePanel point={pin ?? hover} window={window} original={original} refined={refined} showingOriginal={!showingResult}
          fields={conditions.fields} active={conditions.active} source={conditions.conditionSource?.source} />}
        onClearPoint={pin ? () => setPin(null) : undefined}
        layers={<RegionLayerPanel availableBase={conditions.available} value={conditions.active} onSelect={conditions.setSelected}
          conditions={conditions.conditionSource} rasterSize={conditions.raster && `${conditions.raster.width} × ${conditions.raster.height}`}
          notice={result ? result.conditioning ? result.conditioning.climate ? undefined : 'elevationOnly' : 'missingGrid' : undefined}
          compare={refined ? { original: !showingResult, onChange: original => setShowRefined(!original) } : undefined}
          graticule={{ opacity: graticule, onChange: setGraticule }} />}
        regionTools={<>
          <div className="space-y-1">
            <p className="font-medium text-gray-200">{t(showingResult ? 'packs.refinement.adopted' : 'packs.export.global')}</p>
            <p className="lg:hidden">{t('regionWindow.summary', { lat, lon, spanKm })}</p>
            <p>{t(showingResult ? 'packs.compute.refinedHint' : 'packs.export.globalHint')}</p>
          </div>
          <TerrainCompute browser={{ raster: preview?.raster ?? null, spanKm, seaLevel: sea,
            nativeEstimateKm, worldSource: { world, planet, branch, window, browserWorld: meta.data?.browser_heightmap, climateResult },
            sourceRowSpacingKm: preview && preview.sourceHeight > 1 ? stepKm : null, onResult: (result) => {
            setTemporary(result)
            setRequestedSource(currentBrowserRefinement)
            setShowRefined(true)
            conditions.setSelected('mapElevation')
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
            {current === currentBrowserRefinement && temporary && preview && <SaveProjectResult result={temporary} target={{ worldId: world, planet, branch,
              browserWorld: meta.data?.browser_heightmap,
              climateResult,
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
        {preview || saved ? <><PackMap window={window} base={conditions.layer ? conditions.preview : savedRasters.isError ? null : base}
          loading={conditions.layer ? !conditions.preview : !savedRasters.isError && (!displayed || !base)} context={context}
          rivers={null} graticuleOpacity={graticule} pin={pin} onHover={setHover} onLockPoint={setPin} />
          {savedRasters.isError && <p role="alert" className="absolute left-3 top-3 z-[500] rounded border border-space-border bg-space-bg px-2 py-1 text-xs text-red-300">
            {t('packs.results.unreadable')}
          </p>}</> : (
          <div className="absolute inset-0 grid place-content-center gap-2 p-4 text-center text-sm text-gray-400">
            <p role={missing || height.failed ? 'alert' : 'status'}>{t(missing ? 'packs.export.missing' : height.failed ? 'packs.export.previewFailed' : 'status.loading')}</p>
            {height.failed && <button type="button" className="min-h-11 text-neon-cyan hover:underline" onClick={height.retry}>{t('packs.export.retry')}</button>}
          </div>
        )}
      </RegionMapWorkspace>
  )
}
