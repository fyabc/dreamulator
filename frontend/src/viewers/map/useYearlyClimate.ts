/**
 * useYearlyClimate — load the per-cell UCC climate descriptors
 * (`climate_yearly.msgpack`, UCC-01 step 2).
 *
 * Unlike `useMonthlyClimate` this fetch is independent of the monthly display
 * mode: the descriptors are the cell inspector's「气候描述」data source, so the
 * (small) file is fetched whenever a planet map is open.  A missing file —
 * e.g. the Earth reference root, which is never built, or a branch whose maps
 * fall back to the root — resolves to null and the panel degrades gracefully.
 */

import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'

export function useYearlyClimate(
  worldName: string | undefined,
  planetId: string | null | undefined,
  branch: string | null,
) {
  const { data } = useQuery({
    queryKey: ['yearlyClimate', worldName, planetId, branch],
    queryFn: () => api.getYearlyClimate(worldName!, planetId!, branch),
    enabled: !!worldName && !!planetId,
    retry: false,
  })
  return data ?? null
}
