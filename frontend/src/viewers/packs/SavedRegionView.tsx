import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import AtlasIcon from '../../components/AtlasIcon'
import MapHelpLink from '../../components/map/MapHelpLink'
import RegionElevationDownload from '../../components/map/RegionElevationDownload'
import SaveProjectResult, { projectButton } from '../../components/projects/SaveProjectResult'
import { elevationSource, openProjectRaster, type ElevationSource, type ProjectLayer } from '../../projects/elevationProject'
import { getProject, projectKey, worldDataPath } from '../../projects/projectStore'
import { downloadBlob } from '../../utils/downloadBlob'
import PackMap from './PackMap'
import RegionMapWorkspace from './RegionMapWorkspace'
import TerrainCompute, { type BrowserTerrainResult } from './TerrainCompute'
import { useElevationPreview } from './useElevationPreview'
import { useRegionElevation, type ElevationInput } from './useRegionElevation'

const ignorePoint = () => undefined
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

  return <div className="flex min-h-[calc(100dvh-56px)] flex-col md:h-[100dvh]">
    <header className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-b border-space-border bg-space-panel px-3 py-2 sm:px-4">
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-4">
        <h1 className="text-sm font-semibold text-gray-200">{map('packs.pickPrompt')}</h1>
        <Link ref={focusReturn} to={projectId ? worldDataPath(projectId, branch) : '/worlds'}
          className="inline-flex min-h-9 items-center gap-1.5 text-xs text-neon-cyan hover:underline">
          <AtlasIcon name="back" className="size-4" />{projectId ? t('backToData') : map('packs.entry.openWorlds')}
        </Link>
      </div>
      <MapHelpLink section="packs" label={map('packs.help')} />
    </header>
    {projectId && layerId && project.isPending ? <p role="status" className="p-4 text-sm text-gray-300">{t('loading')}</p>
      : layer && source ? <SavedElevationMap projectId={projectId} layer={layer} source={source} branch={branch} />
      : <p role="alert" className="p-4 text-sm text-gray-300">{t(project.isError ? 'unreadable' : 'layerUnavailable')}</p>}
  </div>
}

function SavedElevationMap({ projectId, layer, source, branch }: {
  projectId: string
  layer: ProjectLayer
  source: ElevationSource
  branch: string | null
}) {
  const { t } = useTranslation('worlds', { keyPrefix: 'worldData' })
  const { t: map } = useTranslation('map')
  const [temporary, setTemporary] = useState<BrowserTerrainResult | null>(null)
  const [compare, setCompare] = useState(false)
  const { window, min, max, sea, sourceStepKm } = source.frame
  const span = window.extentKmX
  const sourceRaster = useQuery({ queryKey: ['project-raster', projectId, source.id], queryFn: () => openProjectRaster(source),
    retry: false, staleTime: Infinity, gcTime: 0 })
  const result = useQuery({ queryKey: ['project-raster', projectId, layer.id], queryFn: () => openProjectRaster(layer),
    enabled: layer.kind === 'elevation-result', retry: false, staleTime: Infinity, gcTime: 0 })
  const selected = temporary?.raster ?? (layer.kind === 'elevation-result' ? result.data : sourceRaster.data)
  const displayed = (compare ? sourceRaster.data : selected) ?? null
  const preview = useElevationPreview(displayed, min, max, sea)
  const input = useMemo<ElevationInput | null>(() => selected ? { kind: 'project-raster', raster: selected } : null, [selected])
  const exporter = useRegionElevation(input)
  const settings = temporary ?? (layer.kind === 'elevation-result' ? layer.settings : null)

  return <RegionMapWorkspace toolsLabel={map('packs.entry.tools')} tools={<>
    <div className="space-y-1">
      <h2 className="break-words text-sm font-semibold text-gray-200">{layer.name}</h2>
      <p>{t('extent', { lat: window.centerLat, lon: window.centerLon, span, sea })}</p>
      {source.location && <p className="break-words">
        {t('location', { planet: source.location.planet, branch: source.location.branch ?? t('mainBranch') })}
      </p>}
      {selected && <p>{t('dimensions', { width: selected.width, height: selected.height })}</p>}
    </div>
    {(sourceRaster.isError || result.isError) && <p role="alert">{t('unreadable')}</p>}
    {settings && <label className="flex flex-wrap items-center gap-2">{map('packs.refinement.compare')}
      <select className="min-h-11 max-w-full rounded border border-space-border bg-space-surface p-1 text-gray-200 md:min-h-8"
        value={compare ? 'input' : 'result'} onChange={(event) => setCompare(event.target.value === 'input')}>
        <option value="result">{map('packs.refinement.adopted')}</option>
        <option value="input">{map('packs.refinement.original')}</option>
      </select>
    </label>}
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
    {layer.kind === 'elevation-source' && <TerrainCompute browser={{ raster: sourceRaster.data ?? null, spanKm: span, seaLevel: sea,
      sourceRowSpacingKm: sourceStepKm, onResult: (result) => { setTemporary(result); setCompare(false) } }} />}
  </>}>
    <PackMap window={window} base={preview} rivers={null} graticuleOn zoomSnap={0.25} pin={null} onHover={ignorePoint} onProbe={ignorePoint} />
  </RegionMapWorkspace>
}
