/**
 * MapCellInspector — displays properties of the hovered/selected Voronoi cell.
 */

import type { VoronoiCell, TectonicPlate } from '../../viewers/map/types'
import { normalisedToMeters } from '../../viewers/map/utils/projection'

interface MapCellInspectorProps {
  cell: VoronoiCell | null
  plate: TectonicPlate | null
  elevMinM: number
  elevMaxM: number
}

export default function MapCellInspector({
  cell,
  plate,
  elevMinM,
  elevMaxM,
}: MapCellInspectorProps) {
  if (!cell) {
    return (
      <div className="text-xs text-gray-600 p-2 space-y-2">
        <p className="italic">悬停地图上的单元格查看详情</p>
        <p className="text-gray-700">
          提示：需要先在左侧面板开启「Voronoi 网格」叠加层，才能在地图上悬停和查看单元格属性。
        </p>
      </div>
    )
  }

  const elevM = Math.round(normalisedToMeters(cell.elevation, elevMinM, elevMaxM))
  const isLand = cell.elevation > 0.4 // approximate

  return (
    <div className="space-y-2 text-sm">
      <div className="flex items-center gap-2">
        <span className="text-neon-cyan font-semibold">Cell #{cell.id}</span>
        <span
          className={`text-xs px-1.5 py-0.5 rounded ${
            isLand
              ? 'bg-green-900/30 text-green-300'
              : 'bg-blue-900/30 text-blue-300'
          }`}
        >
          {isLand ? '陆地' : '海洋'}
        </span>
      </div>

      <dl className="space-y-1 text-xs">
        <div className="flex justify-between">
          <dt className="text-gray-500">经度</dt>
          <dd className="font-mono">{cell.lon.toFixed(1)}°</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500">纬度</dt>
          <dd className="font-mono">{cell.lat.toFixed(1)}°</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500">海拔</dt>
          <dd className="font-mono">{elevM.toLocaleString()} m</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500">湿度</dt>
          <dd className="font-mono">{(cell.moisture * 100).toFixed(0)}%</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500">邻居</dt>
          <dd className="font-mono">{cell.neighbors.length}</dd>
        </div>
        {plate && (
          <>
            <div className="border-t border-space-border pt-1 mt-1" />
            <div className="flex justify-between">
              <dt className="text-gray-500">板块</dt>
              <dd className="text-amber-300">{plate.name}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-gray-500">类型</dt>
              <dd className="font-mono">{plate.type}</dd>
            </div>
          </>
        )}
        {cell.biome && (
          <div className="flex justify-between">
            <dt className="text-gray-500">生态</dt>
            <dd>{cell.biome}</dd>
          </div>
        )}
        {cell.province_id && (
          <div className="flex justify-between">
            <dt className="text-gray-500">省份</dt>
            <dd>{cell.province_id}</dd>
          </div>
        )}
      </dl>
    </div>
  )
}
