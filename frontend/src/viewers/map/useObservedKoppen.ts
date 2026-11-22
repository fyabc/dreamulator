import { useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'
import { makeTexture } from './layerBakes'
import { observedKoppenPixels, readObservedKoppen } from './observedKoppen'

export function useObservedKoppen(world: string | undefined, planet: string, branch: string | null, enabled: boolean,
  maxWidth?: number) {
  const { data, isFetching, isError } = useQuery({
    queryKey: ['observedKoppen', world, planet, branch],
    queryFn: async ({ signal }) => readObservedKoppen(await api.getObservedKoppen(world!, planet, branch, signal)),
    enabled: enabled && !!world && !!planet,
    staleTime: 5 * 60_000,
    retry: false,
  })
  const texture = useMemo(() => {
    if (!enabled || !data) return null
    const scale = maxWidth && maxWidth < data.width ? maxWidth / data.width : 1
    return makeTexture(observedKoppenPixels(data, maxWidth),
      Math.max(1, Math.round(data.width * scale)), Math.max(1, Math.round(data.height * scale)),
      { nearestMag: true })
  }, [enabled, data, maxWidth])
  useEffect(() => () => texture?.dispose(), [texture])
  return { texture, pending: enabled && isFetching && !texture, failed: enabled && isError && !texture }
}
