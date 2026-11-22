import { describe, expect, it } from 'vitest'
import { guideForRoute, markMilestone, observeTutorialRoute, type TutorialProgress } from './tutorialProgress'

const world = 'guide-earth'
const planet = 'planet_terra'
const branch = 'tilt'
const overviewPath = `/worlds/${world}`
const mapPath = `${overviewPath}/map/${planet}`
const regionSearch = `?world=${world}&planet=${planet}&branch=${branch}&window=24.1%2C121.45%2C150`

describe('workflow tutorial', () => {
  it('advances the local workflow through completed operations and scoped routes', () => {
    const importStep: TutorialProgress = { flow: 'local', step: 'source' }
    const parameters = markMilestone(importStep, { type: 'imported', world })
    expect(parameters.step).toBe('parameters')
    expect(observeTutorialRoute(parameters, '/worlds/other', '?tab=parameters')).toBe(parameters)
    const build = observeTutorialRoute({ ...parameters, muted: true }, overviewPath, '?tab=parameters')
    expect(build).toMatchObject({ step: 'build', muted: false })
    expect(guideForRoute(build, overviewPath, '?tab=astronomy')).toMatchObject({ active: false, to: `${overviewPath}?tab=parameters` })
    expect(markMilestone(build, { type: 'built', world, branch })).toBe(build)
    const map = markMilestone(build, { type: 'built', world })
    expect(map.step).toBe('map')
    expect(observeTutorialRoute(map, mapPath, '?creation=1')).toBe(map)
    const monthly = observeTutorialRoute(map, mapPath, '?layer=temperature')
    expect(monthly).toMatchObject({ planet, step: 'monthly' })
    const climate = observeTutorialRoute(monthly, mapPath, '?monthly=1')
    expect(climate.step).toBe('climate')
    expect(guideForRoute(climate, '/help', '')).toMatchObject({ active: false, to: `${mapPath}?layer=temperature&trial=climate` })
    const region = markMilestone(climate, { type: 'forked', world, planet, base: null, branch })
    expect(region).toMatchObject({ step: 'region', branch })
    expect(observeTutorialRoute(region, '/packs', regionSearch.replace(branch, 'other'))).toBe(region)
    const refine = observeTutorialRoute(region, '/packs', regionSearch)
    expect(refine).toMatchObject({ step: 'refine', region: regionSearch })
    expect(guideForRoute(refine, '/packs', regionSearch).anchors.slice(-1)).toEqual(['regionTools'])
    expect(guideForRoute(refine, '/help', '')).toMatchObject({ active: false, to: `/packs${regionSearch}` })
    expect(markMilestone(refine, { type: 'regionResult', world, planet, branch: null })).toBe(refine)
    const backup = markMilestone(refine, { type: 'regionResult', world, planet, branch })
    expect(guideForRoute(backup, '/packs', regionSearch)).toMatchObject({ chapter: 4, active: false, to: overviewPath })
    expect(guideForRoute(backup, overviewPath, '?tab=data')).toMatchObject({ active: false, to: overviewPath })
    expect(markMilestone(backup, { type: 'backup', world }).step).toBe('done')
  })

  it('keeps browser creation separate from formal construction and backup', () => {
    const map = markMilestone({ flow: 'browser', step: 'source' }, { type: 'imported', world })
    expect(map.step).toBe('browserMap')
    expect(guideForRoute(map, overviewPath, '')).toMatchObject({ active: true, to: overviewPath, anchors: ['browserMap'] })
    expect(markMilestone(map, { type: 'built', world })).toBe(map)
    expect(observeTutorialRoute(map, mapPath, '?branch=other')).toBe(map)
    const view = observeTutorialRoute(map, mapPath, '')
    expect(observeTutorialRoute(map, mapPath, '?creation=1')).toEqual(view)
    expect(view.step).toBe('browserView')
    const backup = observeTutorialRoute(view, overviewPath, '?tab=data')
    expect(guideForRoute(backup, overviewPath, '?tab=data')).toMatchObject({ active: true, chapter: 2, anchors: ['browserBackup'] })
    expect(markMilestone(backup, { type: 'backup', world: 'other' })).toBe(backup)
    expect(markMilestone(backup, { type: 'backup', world }).step).toBe('done')
  })
})
