/**
 * MapStatusBar — shows cursor position, elevation, and hovered cell data.
 *
 * When a cell is hovered, displays geographic + geological properties.
 * Otherwise shows a placeholder prompt.
 */

import { useTranslation } from 'react-i18next'
import type { CursorInfo } from './MapViewer'
import type { VoronoiCell } from '../../viewers/map/types'

const CRUST_LABELS: Record<string, string> = {
  continental: 'crust.continental',
  oceanic: 'crust.oceanic',
  transitional: 'crust.transitional',
}

interface MapStatusBarProps {
  cursor: CursorInfo | null
  zoom: number
  /** Currently hovered Voronoi cell (from cvtMesh) for geological info. */
  hoveredCell: VoronoiCell | null
}

export default function MapStatusBar({
  cursor,
  zoom,
  hoveredCell,
}: MapStatusBarProps) {
  const { t } = useTranslation('map')

  const crustLabel = hoveredCell?.crust_type
    ? (CRUST_LABELS[hoveredCell.crust_type] ? t(CRUST_LABELS[hoveredCell.crust_type]) : hoveredCell.crust_type)
    : '—'

  if (!cursor) {
    return (
      <div className="flex items-center gap-4 px-3 py-1.5 bg-space-panel/80 border-t border-space-border text-xs text-gray-500 font-mono">
        <span>{t('status.hoverPrompt')}</span>
        <span className="ml-auto text-gray-600">{t('field.zoom')} {zoom.toFixed(1)}x</span>
      </div>
    )
  }

  return (
    <div className="flex items-center gap-3 px-3 py-1.5 bg-space-panel/80 border-t border-space-border text-xs text-gray-400 font-mono">
      <span>
        {t('field.longitude')} {cursor.lon.toFixed(2)}°
      </span>
      <span className="text-gray-600">|</span>
      <span>
        {t('field.latitude')} {cursor.lat.toFixed(2)}°
      </span>
      <span className="text-gray-600">|</span>
      <span
        className={
          cursor.elevationM >= 0 ? 'text-green-400' : 'text-blue-400'
        }
      >
        {t('field.elevation')} {cursor.elevationM >= 0 ? '+' : ''}
        {cursor.elevationM.toLocaleString()}m
      </span>

      {hoveredCell && (
        <>
          <span className="text-gray-600">|</span>
          <span className="text-amber-300/80">
            {t('field.crust')} {crustLabel}
          </span>
          <span className="text-gray-600">|</span>
          <span className="text-amber-300/80">
            {t('field.plate')} {hoveredCell.plate_id ?? '—'}
          </span>
        </>
      )}

      <span className="ml-auto text-gray-500">{t('field.zoom')} {zoom.toFixed(1)}x</span>
    </div>
  )
}
