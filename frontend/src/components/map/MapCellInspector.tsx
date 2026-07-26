/**
 * MapCellInspector — two-mode right panel.
 *
 * Mode A (no cell selected): Planet summary card with stats from cvtMesh.
 * Mode B (cell selected): Full cell property table.
 */

import type { VoronoiCell, TectonicPlate, CVTMesh } from '../../viewers/map/types'

interface MapCellInspectorProps {
  cell: VoronoiCell | null
  plate: TectonicPlate | null
  cvtMesh: CVTMesh | null
  /** Planet display name (for summary header). */
  planetName: string | null
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const BOUNDARY_COLORS: Record<string, string> = {
  convergent: 'bg-red-900/40 text-red-300',
  divergent: 'bg-green-900/40 text-green-300',
  transform: 'bg-yellow-900/40 text-yellow-300',
}

const CRUST_LABELS: Record<string, string> = {
  continental: '大陆地壳',
  oceanic: '海洋地壳',
  transitional: '过渡地壳',
}

const BOUNDARY_LABELS: Record<string, string> = {
  convergent: '汇聚边界',
  divergent: '离散边界',
  transform: '转换边界',
}

function formatNumber(n: number | undefined, decimals = 0): string {
  if (n === undefined || n === null) return '—'
  if (!isFinite(n)) return '∞'
  return n.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

// ---------------------------------------------------------------------------
// Mode A — Planet summary
// ---------------------------------------------------------------------------

function PlanetSummary({
  cvtMesh,
  planetName,
}: {
  cvtMesh: CVTMesh | null
  planetName: string | null
}) {
  if (!cvtMesh) {
    return (
      <p className="text-xs text-gray-600 italic p-2">加载网格数据中…</p>
    )
  }

  const cells = cvtMesh.cells
  const totalCells = cells.length

  // Aggregate stats over all cells
  let landCount = 0
  let landArea = 0
  let oceanArea = 0
  let continentalArea = 0
  let oceanicArea = 0
  let elevMin = Infinity
  let elevMax = -Infinity
  const plateIds = new Set<string>()

  for (const c of cells) {
    const area = c.area_km2 ?? 0
    if (c.elevation > 0) {
      landCount++
      landArea += area
    } else {
      oceanArea += area
    }
    if (c.crust_type === 'continental') continentalArea += area
    else oceanicArea += area
    if (c.elevation < elevMin) elevMin = c.elevation
    if (c.elevation > elevMax) elevMax = c.elevation
    if (c.plate_id) plateIds.add(c.plate_id)
  }
  if (!isFinite(elevMin)) elevMin = 0
  if (!isFinite(elevMax)) elevMax = 0

  const totalCellsNum = totalCells
  const landPct = totalCellsNum > 0 ? ((landCount / totalCellsNum) * 100).toFixed(1) : '0'
  const seaPct = totalCellsNum > 0 ? (((totalCellsNum - landCount) / totalCellsNum) * 100).toFixed(1) : '0'
  const totalArea = landArea + oceanArea
  const crustPct = totalArea > 0 ? (continentalArea / totalArea * 100).toFixed(1) : '0'
  const seaLevel = 0
  const peakProminence = elevMax - seaLevel
  const maxOceanDepth = seaLevel - elevMin

  const fmtKm2 = (km2: number) =>
    km2 > 1_000_000
      ? `${(km2 / 1_000_000).toFixed(1)}M km²`
      : `${km2.toLocaleString(undefined, { maximumFractionDigits: 0 })} km²`

  return (
    <div className="space-y-3">
      <div>
        <h4 className="text-sm font-semibold text-neon-cyan">
          {planetName ?? '未知行星'}
        </h4>
        <p className="text-[10px] text-gray-600 font-mono">seed: {cvtMesh.seed}</p>
      </div>

      <dl className="space-y-1.5 text-xs">
        <div className="flex justify-between">
          <dt className="text-gray-500">海陆比例</dt>
          <dd className="font-mono text-right">
            <span className="text-green-400">{landPct}%</span>
            <span className="text-gray-600"> / </span>
            <span className="text-blue-400">{seaPct}%</span>
          </dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500">陆地面积</dt>
          <dd className="font-mono text-right text-green-400">{fmtKm2(landArea)}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500">海洋面积</dt>
          <dd className="font-mono text-right text-blue-400">{fmtKm2(oceanArea)}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500">总表面积</dt>
          <dd className="font-mono text-right">{fmtKm2(totalArea)}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500">陆壳 / 洋壳</dt>
          <dd className="font-mono text-right">
            {crustPct}% / {(100 - Number(crustPct)).toFixed(1)}%
          </dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500">高程范围</dt>
          <dd className="font-mono text-right">
            {formatNumber(Math.round(elevMin))} ~ {formatNumber(Math.round(elevMax))} m
          </dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500">最高点</dt>
          <dd className="font-mono text-right">{formatNumber(Math.round(peakProminence))} m</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500">最深海</dt>
          <dd className="font-mono text-right">{formatNumber(Math.round(maxOceanDepth))} m</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500">板块数</dt>
          <dd className="font-mono">{plateIds.size}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500">网格节点</dt>
          <dd className="font-mono">{cvtMesh.vertices.length.toLocaleString()}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500">单元格数</dt>
          <dd className="font-mono">{totalCells.toLocaleString()}</dd>
        </div>
      </dl>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Mode B — Cell details
// ---------------------------------------------------------------------------

function CellDetails({
  cell,
  plate,
}: {
  cell: VoronoiCell
  plate: TectonicPlate | null
}) {
  const elevM = Math.round(cell.elevation)
  const isLand = cell.elevation > 0
  const boundaryClass = cell.boundary_type
    ? BOUNDARY_COLORS[cell.boundary_type] ?? 'bg-gray-800 text-gray-300'
    : null

  return (
    <div className="space-y-2 text-sm">
      <div className="flex items-center gap-2">
        <span className="text-neon-cyan font-semibold">Cell #{cell.id}</span>
        <span
          className={`text-xs px-1.5 py-0.5 rounded ${
            isLand ? 'bg-green-900/30 text-green-300' : 'bg-blue-900/30 text-blue-300'
          }`}
        >
          {isLand ? '陆地' : '海洋'}
        </span>
      </div>

      <dl className="space-y-1 text-xs">
        <div className="flex justify-between">
          <dt className="text-gray-500">经度</dt>
          <dd className="font-mono">{cell.lon.toFixed(2)}°</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500">纬度</dt>
          <dd className="font-mono">{cell.lat.toFixed(2)}°</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500">海拔</dt>
          <dd className={`font-mono ${elevM >= 0 ? 'text-green-400' : 'text-blue-400'}`}>
            {elevM >= 0 ? '+' : ''}
            {elevM.toLocaleString()} m
          </dd>
        </div>

        <div className="border-t border-space-border pt-1 mt-1" />

        <div className="flex justify-between">
          <dt className="text-gray-500" title="continental=大陆, oceanic=海洋, transitional=过渡带">地壳类型</dt>
          <dd className="font-mono">{CRUST_LABELS[cell.crust_type ?? ''] ?? cell.crust_type ?? '—'}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500" title="该 cell 所属的构造板块">板块</dt>
          <dd className="text-amber-300">
            {plate?.name ?? cell.plate_id ?? '—'}
          </dd>
        </div>
        <div className="flex justify-between items-center">
          <dt className="text-gray-500" title="汇聚(红)=板块挤压, 离散(绿)=板块张裂, 转换(黄)=水平错动">边界类型</dt>
          <dd>
            {cell.boundary_type ? (
              <span className={`text-xs px-1.5 py-0.5 rounded ${boundaryClass}`}>
                {BOUNDARY_LABELS[cell.boundary_type] ?? cell.boundary_type}
              </span>
            ) : (
              <span className="text-gray-600">—</span>
            )}
          </dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500" title="两板块相对运动速度的法向分量">汇聚速率</dt>
          <dd className="font-mono">
            {cell.convergence_rate_cm_yr !== undefined
              ? `${formatNumber(cell.convergence_rate_cm_yr, 1)} cm/yr`
              : '—'}
          </dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500" title="到最近板块边界的球面距离">距边界距离</dt>
          <dd className="font-mono">
            {cell.distance_to_boundary_km !== undefined
              ? isFinite(cell.distance_to_boundary_km)
                ? `${formatNumber(Math.round(cell.distance_to_boundary_km))} km`
                : '∞'
              : '—'}
          </dd>
        </div>
        {(cell.hotspot_id || cell.landform) && (
          <div className="flex justify-between">
            <dt className="text-gray-500" title="特殊地壳类型：热点链 (Wilson 1963) / 古造山带 (Şengör 1990) / 裂谷 (Burke & Dewey 1973)">特殊地壳</dt>
            <dd className={`font-mono text-xs ${
              cell.hotspot_id ? 'text-fuchsia-400' :
              cell.landform === 'orogeny' ? 'text-amber-400' :
              'text-teal-400'
            }`}>
              {cell.hotspot_id ? `热点链 ${cell.hotspot_id}` :
               cell.landform === 'orogeny' ? '古造山带' :
               cell.landform === 'rift' ? '裂谷' : ''}
            </dd>
          </div>
        )}
        <div className="flex justify-between">
          <dt className="text-gray-500">面积</dt>
          <dd className="font-mono">
            {cell.area_km2 !== undefined
              ? `${formatNumber(Math.round(cell.area_km2))} km²`
              : '—'}
          </dd>
        </div>

        {cell.biome && (
          <>
            <div className="border-t border-space-border pt-1 mt-1" />
            <div className="flex justify-between">
              <dt className="text-gray-500">生态</dt>
              <dd>{cell.biome}</dd>
            </div>
          </>
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

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function MapCellInspector({
  cell,
  plate,
  cvtMesh,
  planetName,
}: MapCellInspectorProps) {
  if (!cell) {
    return <PlanetSummary cvtMesh={cvtMesh} planetName={planetName} />
  }
  return <CellDetails cell={cell} plate={plate} />
}
