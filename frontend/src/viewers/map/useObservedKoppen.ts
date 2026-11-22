import { useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'
import { makeTexture } from './layerBakes'
import { observedKoppenPixels, readObservedKoppen } from './observedKoppen'

export function useObservedKoppen(world: string | undefined, planet: string, branch: string | null, enabled: boolean) {
  const { data, isFetching, isError } = useQuery({
    queryKey: ['observedKoppen', world, planet, branch],
    queryFn: async ({ signal }) => readObservedKoppen(await api.getObservedKoppen(world!, planet, branch, signal)),
    enabled: enabled && !!world && !!planet,
    staleTime: 5 * 60_000,
    retry: false,
  })
  const texture = useMemo(() => enabled && data
    ? makeTexture(observedKoppenPixels(data), data.width, data.height, { nearestMag: true }) : null, [enabled, data])
  useEffect(() => () => texture?.dispose(), [texture])
  return { texture, pending: enabled && isFetching && !texture, failed: enabled && isError && !texture }
}
