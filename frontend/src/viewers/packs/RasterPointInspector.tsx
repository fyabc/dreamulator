import { useTranslation } from 'react-i18next'
import type { LonLat } from '../map/utils/mapCoords'
import type { ElevationRaster } from './elevationRaster'
import { lonLatToKm, type PackWindow } from './packCoords'
import { CoordinateFields, FieldGroup, FieldValue } from '../../components/map/MapInspectorFields'

function heightAt(point: LonLat, window: PackWindow, raster?: ElevationRaster) {
  if (!raster) return undefined
  const { x, y } = lonLatToKm(point, window)
  const column = Math.min(raster.width - 1, Math.max(0, Math.floor((0.5 + x / window.extentKmX) * raster.width)))
  const row = Math.min(raster.height - 1, Math.max(0, Math.floor((0.5 - y / window.extentKmY) * raster.height)))
  const value = raster.values[row * raster.width + column]
  return Number.isFinite(value) ? value : undefined
}

export default function RasterPointInspector({ point, original, refined, window }: {
  point: LonLat | null; original?: ElevationRaster; refined?: ElevationRaster; window: PackWindow
}) {
  const { t } = useTranslation('map')
  if (!point) return <p className="text-xs leading-relaxed text-gray-400">{t('packs.rasterProbePrompt')}</p>
  const before = heightAt(point, window, original)
  const after = heightAt(point, window, refined)
  return <div className="space-y-2">
    <FieldGroup icon="compass" label={t('inspector.position')} defaultOpen><CoordinateFields point={point} digits={4} /></FieldGroup>
    {(before !== undefined || after !== undefined) && <FieldGroup icon="geology" label={t('layer.terrain')} defaultOpen>
      {before !== undefined && <FieldValue label={t(refined ? 'packs.refinement.original' : 'packs.field.height')}>{before.toFixed(1)} m</FieldValue>}
      {after !== undefined && <FieldValue label={t('packs.refinement.adopted')}>{after.toFixed(1)} m</FieldValue>}
      {before !== undefined && after !== undefined && <FieldValue label={t('packs.layers.heightChange')}>
        {after >= before ? '+' : ''}{(after - before).toFixed(1)} m
      </FieldValue>}
    </FieldGroup>}
  </div>
}
