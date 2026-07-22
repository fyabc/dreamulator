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

  // Land/sea ratio (elevation > 0 = land in absolute metres)
  const landCount = cells.filter((c) => c.elevation > 0).length
  const landPct = totalCells > 0 ? ((landCount / totalCells) * 100).toFixed(1) : '0'
  const seaPct = totalCells > 0 ? (((totalCells - landCount) / totalCells) * 100).toFixed(1) : '0'

  // Elevation range
  let elevMin = Infinity
  let elevMax = -Infinity
  for (const c of cells) {
    if (c.elevation < elevMin) elevMin = c.elevation
    if (c.elevation > elevMax) elevMax = c.elevation
  }
  if (!isFinite(elevMin)) elevMin = 0
  if (!isFinite(elevMax)) elevMax = 0

  // Unique plate count
  const plateIds = new Set<string>()
  for (const c of cells) {
    if (c.plate_id) plateIds.add(c.plate_id)
  }

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
          <dt className="text-gray-500">高程范围</dt>
          <dd className="font-mono text-right">
            {formatNumber(Math.round(elevMin))} ~ {formatNumber(Math.round(elevMax))} m
          </dd>
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
          <dt className="text-gray-500">地壳类型</dt>
          <dd className="font-mono">{CRUST_LABELS[cell.crust_type ?? ''] ?? cell.crust_type ?? '—'}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500">板块</dt>
          <dd className="text-amber-300">
            {plate?.name ?? cell.plate_id ?? '—'}
          </dd>
        </div>
        <div className="flex justify-between items-center">
          <dt className="text-gray-500">边界类型</dt>
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
          <dt className="text-gray-500">汇聚速率</dt>
          <dd className="font-mono">
            {cell.convergence_rate_cm_yr !== undefined
              ? `${formatNumber(cell.convergence_rate_cm_yr, 1)} cm/yr`
              : '—'}
          </dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500">距边界距离</dt>
          <dd className="font-mono">
            {cell.distance_to_boundary_km !== undefined
              ? isFinite(cell.distance_to_boundary_km)
                ? `${formatNumber(Math.round(cell.distance_to_boundary_km))} km`
                : '∞'
              : '—'}
          </dd>
        </div>
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
