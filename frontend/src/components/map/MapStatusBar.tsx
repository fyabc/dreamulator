/**
 * MapStatusBar — shows cursor position, elevation, and zoom level.
 */

import type { CursorInfo } from './MapViewer'

interface MapStatusBarProps {
  cursor: CursorInfo | null
  zoom: number
}

export default function MapStatusBar({ cursor, zoom }: MapStatusBarProps) {
  if (!cursor) {
    return (
      <div className="flex items-center gap-4 px-3 py-1.5 bg-space-panel/80 border-t border-space-border text-xs text-gray-500 font-mono">
        <span>经度: —</span>
        <span>纬度: —</span>
        <span>海拔: —</span>
        <span className="ml-auto text-gray-600">拖拽平移 · 滚轮缩放</span>
        <span className="text-gray-500">缩放: {zoom.toFixed(1)}x</span>
      </div>
    )
  }

  const lonDir = cursor.lon >= 0 ? 'E' : 'W'
  const latDir = cursor.lat >= 0 ? 'N' : 'S'

  return (
    <div className="flex items-center gap-4 px-3 py-1.5 bg-space-panel/80 border-t border-space-border text-xs text-gray-400 font-mono">
      <span>
        {Math.abs(cursor.lon).toFixed(2)}° {lonDir}
      </span>
      <span>
        {Math.abs(cursor.lat).toFixed(2)}° {latDir}
      </span>
      <span
        className={
          cursor.elevationM >= 0 ? 'text-green-400' : 'text-blue-400'
        }
      >
        {cursor.elevationM >= 0 ? '+' : ''}
        {cursor.elevationM.toLocaleString()} m
      </span>
      <span className="text-gray-600">
        px({cursor.pixelX}, {cursor.pixelY})
      </span>
      <span className="ml-auto text-gray-500">缩放: {zoom.toFixed(1)}x</span>
    </div>
  )
}
