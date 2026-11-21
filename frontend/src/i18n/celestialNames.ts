import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'

type CelestialNames = Record<string, Record<string, string>>

export function resolveCelestialName(
  names: CelestialNames | undefined,
  world: string | undefined,
  id: string,
  original?: string | null,
): string {
  const translated = world ? names?.[world]?.[id] : undefined
  return typeof translated === 'string' && translated !== '' ? translated : original || id
}

export function useCelestialName(world: string | undefined) {
  const { i18n } = useTranslation('celestial')
  const names = i18n.getResourceBundle(i18n.resolvedLanguage ?? i18n.language, 'celestial') as CelestialNames | undefined
  return useCallback(
    (id: string, original?: string | null) => resolveCelestialName(names, world, id, original),
    [names, world],
  )
}
