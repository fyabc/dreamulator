/**
 * MapStatusBar — shows cursor position, elevation, and hovered cell data.
 *
 * When a cell is hovered, displays geographic + geological properties.
 * Otherwise shows a placeholder prompt.
 */

import type { CursorInfo } from './MapViewer'
import type { VoronoiCell } from '../../viewers/map/types'

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
  if (!cursor) {
    return (
      <div className="flex items-center gap-4 px-3 py-1.5 bg-space-panel/80 border-t border-space-border text-xs text-gray-500 font-mono">
        <span>移动鼠标查看单元格信息</span>
        <span className="ml-auto text-gray-600">缩放: {zoom.toFixed(1)}x</span>
      </div>
    )
  }

  return (
    <div className="flex items-center gap-3 px-3 py-1.5 bg-space-panel/80 border-t border-space-border text-xs text-gray-400 font-mono">
      <span>
        经度: {cursor.lon.toFixed(2)}°
      </span>
      <span className="text-gray-600">|</span>
      <span>
        纬度: {cursor.lat.toFixed(2)}°
      </span>
      <span className="text-gray-600">|</span>
      <span
        className={
          cursor.elevationM >= 0 ? 'text-green-400' : 'text-blue-400'
        }
      >
        海拔: {cursor.elevationM >= 0 ? '+' : ''}
        {cursor.elevationM.toLocaleString()}m
      </span>

      {hoveredCell && (
        <>
          <span className="text-gray-600">|</span>
          <span className="text-amber-300/80">
            地壳: {hoveredCell.crust_type ?? '—'}
          </span>
          <span className="text-gray-600">|</span>
          <span className="text-amber-300/80">
            板块: {hoveredCell.plate_id ?? '—'}
          </span>
        </>
      )}

      <span className="ml-auto text-gray-500">缩放: {zoom.toFixed(1)}x</span>
    </div>
  )
}
