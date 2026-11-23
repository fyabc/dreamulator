import { describe, expect, it } from 'vitest'
import { RESULT_MODE_PARAM, resolveMapMode, resultModeValue } from './useTemperatureTrialPreview'

describe('map result mode in the URL', () => {
  it('uses an explicit URL choice', () => {
    expect(resolveMapMode('development', null)).toBe('trial')
    expect(resolveMapMode('official', 'saved')).toBe('official')
  })

  it('falls back to a saved result, then the official build', () => {
    expect(resolveMapMode(null, 'saved')).toBe('trial')
    expect(resolveMapMode(null, null)).toBe('official')
    expect(resolveMapMode('unknown', 'saved')).toBe('trial')
  })

  it('writes development for the internal trial mode', () => {
    expect(resultModeValue('trial')).toBe('development')
    expect(resultModeValue('official')).toBe('official')
    expect(RESULT_MODE_PARAM).toBe('result')
  })
})
