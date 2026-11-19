import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api } from '../../api/client'
import RegionElevationDownload from '../../components/map/RegionElevationDownload'
import type { PackInputMeta, PackHeightSource, PackSummary } from './types'
import { useRegionElevation, type ElevationInput } from './useRegionElevation'

export default function PackElevationDownload({ pack, source, input, summary }: {
  pack: string; source: PackHeightSource; input: PackInputMeta; summary: PackSummary | null
}) {
  const { t } = useTranslation('map')
  const [open, setOpen] = useState(false)
  const query = useQuery({ queryKey: ['packElevation', pack, source], queryFn: () => api.getPackElevation(pack, source),
    enabled: open, retry: false, gcTime: 0 })
  const raster = useMemo<ElevationInput | null>(() => query.data ? { kind: 'pack', blob: query.data } : null, [query.data])
  const height = useRegionElevation(raster)
  const ready = height.ready?.kind === 'ready' ? height.ready : null
  const extent = Math.max(input.extent_km.x, input.extent_km.y)
  return (
    <details className="rounded border border-space-border p-2 text-xs text-gray-400" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className="cursor-pointer font-medium text-neon-cyan">{t('packs.export.title')}</summary>
      <div className="mt-2 space-y-2">
        <p>{t(`packs.export.source.${source}`)}</p>
        {ready ? <RegionElevationDownload original={ready} defaultSize={null} extentKm={extent}
          sourceStepKm={extent / Math.max(ready.width, ready.height)} exporting={height.exporting} failed={height.failed}
          onDownload={(size, format) => height.download(`${pack}-${source}${size === null ? '' : `-${size}`}`, size, format, {
            pack, source, world: summary?.world, planet: summary?.planet, branch: summary?.branch,
            projection: input.projection ?? 'local_equirectangular', center_lat: input.center_lat,
            center_lon: input.center_lon, radius_km: input.radius_km ?? 6371, extent_km: input.extent_km,
            sea_level_m: input.sea_level_m, sampling: size === null ? 'native' : 'bilinear',
          })} /> : query.isError || height.failed ? <>
          <p role="alert" className="text-red-300">{t('packs.export.failed')}</p>
          <button type="button" className="text-neon-cyan hover:underline"
            onClick={() => query.isError ? void query.refetch() : height.retry()}>{t('packs.export.retry')}</button>
        </> : <p role="status">{t('status.loading')}</p>}
      </div>
    </details>
  )
}
