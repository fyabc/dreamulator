import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { downloadBlob } from '../../utils/downloadBlob'
import { openProjectRaster, type ElevationSource, type ProjectLayer } from '../../projects/elevationProject'
import TerrainCompute, { type BrowserTerrainResult } from '../../viewers/packs/TerrainCompute'
import { useElevationPreview } from '../../viewers/packs/useElevationPreview'
import { useRegionElevation, type ElevationInput } from '../../viewers/packs/useRegionElevation'
import PackMap from '../../viewers/packs/PackMap'
import RegionElevationDownload from '../map/RegionElevationDownload'
import SaveProjectResult, { projectButton } from './SaveProjectResult'

const ignorePoint = () => undefined

export default function ProjectElevationView({ projectId, layer, source }: { projectId: string; layer: ProjectLayer; source: ElevationSource }) {
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

  return <section className="min-w-0 space-y-3 rounded border border-space-border bg-space-panel p-3">
    <h2 className="break-words font-semibold">{layer.name}</h2>
    <p className="text-sm text-gray-400">{t('extent', { lat: window.centerLat, lon: window.centerLon, span, sea })}</p>
    {(sourceRaster.isError || result.isError) && <p role="alert">{t('unreadable')}</p>}
    {settings && <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
      <dt>{map('packs.compute.method.label')}</dt><dd>{map(`packs.compute.method.${settings.recipe.method}`)}</dd>
      <dt>{map('packs.compute.parameters.seed')}</dt><dd>{settings.recipe.seed}</dd>
      <dt>{map('packs.compute.method.nativeSpacing')}</dt><dd>{settings.nativeSpacingKm ?? map('packs.compute.method.unknown')}</dd>
      {settings.recipe.method === 'enhanced' && <><dt>{map('packs.compute.parameters.gain')}</dt><dd>{settings.recipe.residualGain}</dd></>}
      {settings.recipe.method === 'blend' && <><dt>{map('packs.compute.parameters.wavelength')}</dt><dd>{settings.recipe.preserveKm}</dd></>}
      <dt>{t('modelVersion')}</dt><dd className="break-all font-mono text-xs" title={settings.manifestSha256}>{settings.manifestSha256.slice(0, 12)}</dd>
    </dl>}
    {settings && <label className="flex items-center gap-2 text-sm">
      <input type="checkbox" checked={compare} onChange={(event) => setCompare(event.currentTarget.checked)} />{t('compareOriginal')}
    </label>}
    <div className="relative h-[min(58vh,36rem)] min-h-64 overflow-hidden rounded bg-space-bg">
      <PackMap window={window} base={preview} rivers={null} graticuleOn pin={null} onHover={ignorePoint} onProbe={ignorePoint} />
    </div>
    {selected && <p className="text-sm text-gray-400">{t('dimensions', { width: selected.width, height: selected.height })}</p>}
    {source.original && <button type="button" className={projectButton}
      onClick={() => { if (source.original) downloadBlob(source.original.data, source.original.name) }}>{t('downloadSource')}</button>}
    {selected && exporter.ready && <div className="text-sm">
      <RegionElevationDownload fixedSize defaultSize={null} sourceStepKm={span / selected.width} extentKm={span}
        exporting={exporter.exporting} failed={exporter.failed} onDownload={(_, format) => exporter.download(layer.name, null, format, {
          projection: window.projection, center_lat: window.centerLat, center_lon: window.centerLon, radius_km: window.radiusKm,
          extent_km: { x: span, y: span }, sea_level_m: sea, pixel_size_m: span * 1000 / selected.width,
          ...(settings && { seed: settings.recipe.seed, processing_mode: settings.recipe.method,
            model_manifest_sha256: settings.manifestSha256, source_native_spacing_km: settings.nativeSpacingKm,
            decoder_residual_gain: settings.recipe.residualGain,
            ...(settings.recipe.method === 'blend' && { preserve_wavelength_km: settings.recipe.preserveKm }) }),
        })} />
    </div>}
    {temporary && <SaveProjectResult result={temporary} target={{ worldId: projectId, sourceId: source.id }} />}
    {layer.kind === 'elevation-source' && <TerrainCompute browser={{ raster: sourceRaster.data ?? null, spanKm: span, seaLevel: sea,
      sourceRowSpacingKm: sourceStepKm, onResult: (result) => { setTemporary(result); setCompare(false) } }} />}
  </section>
}
