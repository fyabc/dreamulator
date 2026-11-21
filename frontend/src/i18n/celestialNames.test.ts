import { describe, expect, it } from 'vitest'
import { resolveCelestialName } from './celestialNames'
import english from './locales/en/celestial.json'
import chinese from './locales/zh-CN/celestial.json'

describe('resolveCelestialName', () => {
  it('uses the active locale for a catalog body in either world', () => {
    expect(resolveCelestialName(chinese, 'earth', 'planet_earth', 'Earth')).toBe('地球')
    expect(resolveCelestialName(english, 'earth', 'planet_earth', 'Earth')).toBe('Earth')
    expect(resolveCelestialName(chinese, 'nacrea', 'satellite_nacrea', '珠母星 · Nacrea')).toBe('珠母星')
    expect(resolveCelestialName(english, 'nacrea', 'satellite_nacrea', '珠母星 · Nacrea')).toBe('Nacrea')
  })

  it('falls back to the authored name without borrowing from another world or locale', () => {
    expect(resolveCelestialName(chinese, 'other', 'planet_earth', 'Terra')).toBe('Terra')
    expect(resolveCelestialName(undefined, 'earth', 'planet_earth', 'Earth')).toBe('Earth')
    expect(resolveCelestialName(chinese, 'nacrea', 'dwarf_custom', 'Author · Name')).toBe('Author · Name')
    expect(resolveCelestialName(chinese, 'nacrea', 'dwarf_custom', null)).toBe('dwarf_custom')
  })

  it('covers the same world and body IDs in both shipped locales', () => {
    const identifiers = (names: typeof chinese) => Object.entries(names).flatMap(([world, bodies]) =>
      Object.keys(bodies).map((id) => `${world}.${id}`),
    ).sort()
    expect(identifiers(english)).toEqual(identifiers(chinese))
  })
})
