/**
 * CivMapPreview — lightweight entry card for the civilization map.
 *
 * Shows the list of fictional countries with their colors and province counts,
 * plus links to the full editor. Does NOT load GeoJSON or render a Leaflet map
 * (that's too heavy for the WorldDetail page — the full editor handles it).
 */

import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import type { CivCountry, TerritoryAssignment } from './types'
import * as api from '../../api/civmapClient'
import { isStaticMode } from '../../api/mode'
import { staticApi } from '../../api/staticClient'

interface CivMapPreviewProps {
  worldName: string
  branch: string | null
}

export default function CivMapPreview({ worldName, branch }: CivMapPreviewProps) {
  const staticMode = isStaticMode()

  // Only fetch lightweight territory data (no GeoJSON)
  const { data: territory } = useQuery({
    queryKey: ['civmap', 'territory', worldName, branch],
    queryFn: () =>
      staticMode
        ? staticApi.getCivTerritory(worldName, branch) as Promise<any>
        : api.getTerritory(worldName, branch),
    enabled: !!worldName,
  })

  const countries: CivCountry[] = territory?.countries || []
  const activeSnapshotId: string | null = territory?.active_snapshot || null
  const assignments: TerritoryAssignment[] =
    activeSnapshotId && territory?.assignments?.[activeSnapshotId]
      ? territory.assignments[activeSnapshotId]
      : []

  // Count painted provinces per country (must be before any early return — hooks rule)
  const paintCounts = useMemo(() => {
    const counts = new Map<string, number>()
    for (const a of assignments) {
      counts.set(a.country_id, (counts.get(a.country_id) || 0) + 1)
    }
    return counts
  }, [assignments])

  // Only show for branches that have civmap data
  if (territory && countries.length === 0 && (territory?.snapshots?.length ?? 0) === 0) {
    return null
  }

  return (
    <div className="glass-panel p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold text-neon-cyan neon-glow-subtle">
          🏛️ 文明地图
        </h2>
        <div className="flex gap-2">
          {!staticMode && (
            <Link
              to={`/worlds/${worldName}/civmap${branch ? `/${branch}` : ''}`}
              className="px-3 py-1.5 rounded-lg text-sm font-medium bg-neon-cyan/15 text-neon-cyan border border-neon-cyan/30 hover:bg-neon-cyan/25 transition-colors"
            >
              编辑地图 →
            </Link>
          )}
          <Link
            to={`/worlds/${worldName}/civmap${branch ? `/${branch}` : ''}`}
            className="px-3 py-1.5 rounded-lg text-sm text-gray-400 hover:text-gray-200 transition-colors"
          >
            全屏查看
          </Link>
        </div>
      </div>

      {/* Country list */}
      {countries.length > 0 ? (
        <div className="flex flex-wrap gap-3">
          {countries.map((c) => (
            <div key={c.id} className="flex items-center gap-2 text-sm bg-space-surface/60 rounded-lg px-3 py-2 border border-space-border">
              <span
                className="w-4 h-4 rounded shrink-0"
                style={{ backgroundColor: c.color }}
              />
              <span className="text-gray-200 font-medium">{c.name}</span>
              <span className="text-gray-500 text-xs">
                {paintCounts.get(c.id) || 0} 省
              </span>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-gray-500">
          {staticMode
            ? '尚无架空国家数据'
            : '尚无架空国家 — 点击「编辑地图」前往编辑器创建'}
        </p>
      )}

      {staticMode && (
        <p className="mt-3 text-xs text-gray-600">
          只读模式 — 地图编辑仅在 API 模式下可用
        </p>
      )}
    </div>
  )
}
