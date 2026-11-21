import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { isStaticMode } from '../../api/mode'
import RegionElevationDownload from '../../components/map/RegionElevationDownload'
import SaveProjectResult, { projectButton } from '../../components/projects/SaveProjectResult'
import { elevationSource, openProjectRaster, type ElevationSource, type ProjectLayer } from '../../projects/elevationProject'
import { getProject, projectKey, worldDataPath } from '../../projects/projectStore'
import { downloadBlob } from '../../utils/downloadBlob'
import type { LonLat } from '../map/utils/mapCoords'
import PackMap from './PackMap'
import PackStatusBar from './PackStatusBar'
import ProbePanel from './ProbePanel'
import RegionMapWorkspace from './RegionMapWorkspace'
import RegionLayerPanel from './RegionLayerPanel'
import { useRegionContext } from './useRegionContext'
import TerrainCompute, { type BrowserTerrainResult } from './TerrainCompute'
import { useElevationPreview } from './useElevationPreview'
import { useRegionElevation, type ElevationInput } from './useRegionElevation'

const focusReturn = (node: HTMLAnchorElement | null) => node?.focus({ preventScroll: true })

export default function SavedRegionView({ projectId, layerId, branch }: {
  projectId: string
  layerId: string | null
  branch: string | null
}) {
  const { t } = useTranslation('worlds', { keyPrefix: 'worldData' })
  const { t: map } = useTranslation('map')
  const project = useQuery({ queryKey: projectKey(projectId), queryFn: () => getProject(projectId),
    enabled: Boolean(projectId && layerId), retry: false })
  const layer = project.data?.layers.find((item) => item.id === layerId)
  const source = layer && elevationSource(project.data?.layers ?? [], layer)
  const backTo = projectId ? worldDataPath(projectId, branch) : '/worlds'
  const backLabel = projectId ? t('backToData') : map('packs.entry.openWorlds')

  if (layer && source) return <SavedElevationMap projectId={projectId} layer={layer} source={source} branch={branch}
    backTo={backTo} backLabel={backLabel} />

  return <RegionMapWorkspace backTo={backTo} backLabel={backLabel} backRef={focusReturn}>
    {projectId && layerId && project.isPending ? <p role="status" className="p-4 text-sm text-gray-300">{t('loading')}</p>
      : <p role="alert" className="p-4 text-sm text-gray-300">{t(project.isError ? 'unreadable' : 'layerUnavailable')}</p>}
  </RegionMapWorkspace>
}

function SavedElevationMap({ projectId, layer, source, branch, backTo, backLabel }: {
  projectId: string
  layer: ProjectLayer
  source: ElevationSource
  branch: string | null
  backTo: string
  backLabel: string
}) {
  const { t } = useTranslation('worlds', { keyPrefix: 'worldData' })
  const { t: map } = useTranslation('map')
  const [temporary, setTemporary] = useState<BrowserTerrainResult | null>(null)
  const [compare, setCompare] = useState(false)
  const [hover, setHover] = useState<LonLat | null>(null)
  const [pin, setPin] = useState<LonLat | null>(null)
  const [graticule, setGraticule] = useState(0)
  const { window, min, max, sea, sourceStepKm } = source.frame
  const span = window.extentKmX
  const sourceRaster = useQuery({ queryKey: ['project-raster', projectId, source.id], queryFn: () => openProjectRaster(source),
    retry: false, staleTime: Infinity, gcTime: 0 })
  const result = useQuery({ queryKey: ['project-raster', projectId, layer.id], queryFn: () => openProjectRaster(layer),
    enabled: layer.kind === 'elevation-result', retry: false, staleTime: Infinity, gcTime: 0 })
  const selected = temporary?.raster ?? (layer.kind === 'elevation-result' ? result.data : sourceRaster.data)
  const displayed = (compare ? sourceRaster.data : selected) ?? null
  const preview = useElevationPreview(displayed, min, max, sea)
  const context = useRegionContext(source.location ? { world: projectId, ...source.location } : null, window, { min, max, sea })
  const input = useMemo<ElevationInput | null>(() => selected ? { kind: 'project-raster', raster: selected } : null, [selected])
  const exporter = useRegionElevation(input)
  const settings = temporary ?? (layer.kind === 'elevation-result' ? layer.settings : null)

  const unreadable = sourceRaster.isError || result.isError
  const canRefine = layer.kind === 'elevation-source' && isStaticMode()
  return <RegionMapWorkspace backTo={backTo} backLabel={backLabel} backRef={focusReturn} subtitle={layer.name}
    status={<PackStatusBar hover={hover} window={window} />}
    inspector={<ProbePanel point={pin ?? hover} window={window} original={sourceRaster.data}
      refined={settings ? selected : undefined} showingOriginal={compare || displayed === sourceRaster.data} />}
    onClearPoint={pin ? () => setPin(null) : undefined}
    layers={<RegionLayerPanel notice="elevationOnly" graticule={{ opacity: graticule, onChange: setGraticule }}
      compare={settings ? { original: compare, onChange: setCompare } : undefined} />}
    canRefine={canRefine} regionTools={<>
    <div className="space-y-1">
      <h2 className="break-words text-sm font-semibold text-gray-200">{layer.name}</h2>
      <p>{t('extent', { lat: window.centerLat, lon: window.centerLon, span, sea })}</p>
      {source.location && <p className="break-words">
        {t('location', { planet: source.location.planet, branch: source.location.branch ?? t('mainBranch') })}
      </p>}
      {selected && <p>{t('dimensions', { width: selected.width, height: selected.height })}</p>}
    </div>
    {source.original && <button type="button" className={projectButton}
      onClick={() => { if (source.original) downloadBlob(source.original.data, source.original.name) }}>{t('downloadSource')}</button>}
    {selected && exporter.ready && <RegionElevationDownload fixedSize defaultSize={null} sourceStepKm={span / selected.width} extentKm={span}
      downloadLabel={settings ? map('packs.compute.download') : undefined} exporting={exporter.exporting}
      failed={exporter.failed} onDownload={(_, format) => exporter.download(layer.name, null, format, {
        projection: window.projection, center_lat: window.centerLat, center_lon: window.centerLon, radius_km: window.radiusKm,
        extent_km: { x: span, y: window.extentKmY }, sea_level_m: sea, pixel_size_m: span * 1000 / selected.width,
        ...(settings && { seed: settings.recipe.seed, processing_mode: settings.recipe.method,
          model_manifest_sha256: settings.manifestSha256, source_native_spacing_km: settings.nativeSpacingKm,
          decoder_residual_gain: settings.recipe.residualGain,
          ...(settings.recipe.method === 'blend' && { preserve_wavelength_km: settings.recipe.preserveKm }) }),
      })} />}
    {settings && <details className="rounded border border-space-border p-2">
      <summary className="cursor-pointer font-medium text-neon-cyan">{t('resultSettings')}</summary>
      <dl className="mt-2 grid grid-cols-2 gap-x-2 gap-y-1">
        <dt>{map('packs.compute.method.label')}</dt><dd>{map(`packs.compute.method.${settings.recipe.method}`)}</dd>
        <dt>{map('packs.compute.parameters.seed')}</dt><dd>{settings.recipe.seed}</dd>
        <dt>{map('packs.compute.method.nativeSpacing')}</dt><dd>{settings.nativeSpacingKm ?? map('packs.compute.method.unknown')}</dd>
        {settings.recipe.method === 'enhanced' && <><dt>{map('packs.compute.parameters.gain')}</dt><dd>{settings.recipe.residualGain}</dd></>}
        {settings.recipe.method === 'blend' && <><dt>{map('packs.compute.parameters.wavelength')}</dt><dd>{settings.recipe.preserveKm}</dd></>}
        <dt>{t('modelVersion')}</dt><dd className="break-all font-mono" title={settings.manifestSha256}>{settings.manifestSha256.slice(0, 12)}</dd>
      </dl>
    </details>}
    {temporary && <SaveProjectResult result={temporary} target={{ worldId: projectId, sourceId: source.id, branch }} />}
    {canRefine && <TerrainCompute browser={{ raster: sourceRaster.data ?? null, spanKm: span, seaLevel: sea,
      sourceRowSpacingKm: sourceStepKm, onResult: (result) => { setTemporary(result); setCompare(false) } }} />}
  </>}>
    {selected ? <PackMap window={window} base={preview} context={context} rivers={null} graticuleOpacity={graticule}
      pin={pin} onHover={setHover} onLockPoint={setPin} />
      : <p role={unreadable ? 'alert' : 'status'} className="absolute inset-0 grid place-content-center p-4 text-center text-sm text-gray-400">
        {unreadable ? t('unreadable') : map('packs.loadingBase')}
      </p>}
  </RegionMapWorkspace>
}
