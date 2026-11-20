import { useTranslation } from 'react-i18next'
import type { TerrainSource } from '../../viewers/map/elevationSource'

export default function TerrainSourceSelect({ value, onChange, cells, width, height }: {
  value: TerrainSource
  onChange: (value: TerrainSource) => void
  cells?: number
  width: number
  height: number
}) {
  const { t, i18n } = useTranslation('map')
  return (
    <select aria-label={t('terrainSource.label')} title={t('terrainSource.hint')} value={value}
      onChange={(event) => onChange(event.currentTarget.value as TerrainSource)}
      className="min-w-0 rounded border border-space-border bg-space-surface px-2 py-1 text-xs text-gray-300">
      <option value="raster">{t('terrainSource.raster', { width, height })}</option>
      <option value="gray">{t('terrainSource.gray')}</option>
      {!!cells && <option value="mesh">{t('terrainSource.mesh', { cells: new Intl.NumberFormat(i18n.language).format(cells) })}</option>}
    </select>
  )
}
