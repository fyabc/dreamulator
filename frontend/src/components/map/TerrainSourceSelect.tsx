import { useId, useState } from 'react'
import { useTranslation } from 'react-i18next'
import AtlasIcon from '../AtlasIcon'
import type { TerrainSource } from '../../viewers/map/elevationSource'

export default function TerrainSourceSelect({ value, onChange, cells, width, height }: {
  value: TerrainSource
  onChange: (value: TerrainSource) => void
  cells?: number
  width: number
  height: number
}) {
  const { t, i18n } = useTranslation('map')
  const id = useId()
  const helpId = `${id}-help`
  const [helpOpen, setHelpOpen] = useState(false)
  return (
    <div className="relative grid gap-1" onPointerLeave={event => {
      if (event.pointerType === 'mouse') setHelpOpen(false)
    }}>
      <div className="flex items-center gap-1">
        <label htmlFor={id} className="text-xs font-medium text-gray-200">{t('terrainSource.label')}</label>
        <button type="button" aria-label={t('terrainSource.help')} aria-describedby={helpId}
          className="inline-grid size-6 place-items-center rounded text-gray-400 hover:text-neon-cyan focus-visible:outline focus-visible:outline-neon-cyan"
          onPointerEnter={event => { if (event.pointerType === 'mouse') setHelpOpen(true) }}
          onFocus={event => { if (event.currentTarget.matches(':focus-visible')) setHelpOpen(true) }}
          onBlur={() => setHelpOpen(false)} onClick={() => setHelpOpen(true)}
          onKeyDown={event => {
            if (event.key === 'Escape' && helpOpen) {
              event.stopPropagation()
              setHelpOpen(false)
            }
          }}>
          <AtlasIcon name="help" className="size-4" />
        </button>
      </div>
      <select id={id} aria-describedby={helpId} value={value}
        onChange={event => onChange(event.currentTarget.value as TerrainSource)}
        className="min-w-0 rounded border border-space-border bg-space-surface px-2 py-1 text-xs text-gray-300 focus-visible:outline focus-visible:outline-neon-cyan">
        <option value="raster">{t('terrainSource.raster', { width, height })}</option>
        <option value="gray">{t('terrainSource.gray')}</option>
        {!!cells && <option value="mesh">{t('terrainSource.mesh', { cells: new Intl.NumberFormat(i18n.language).format(cells) })}</option>}
      </select>
      <p id={helpId} role="tooltip" className={`${helpOpen ? 'visible' : 'invisible'} absolute inset-x-0 top-full z-20 rounded-md border border-space-border bg-space-surface px-2.5 py-2 text-xs leading-relaxed text-gray-200 shadow-lg`}>
        {t('terrainSource.hint')}
      </p>
    </div>
  )
}
