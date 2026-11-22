import { describe, expect, it } from 'vitest'
import { guideForRoute, markMilestone, observeTutorialRoute, type TutorialProgress } from './tutorialProgress'

const world = 'guide-earth'
const planet = 'planet_terra'
const branch = 'tilt'
const overviewPath = `/worlds/${world}`
const dataSearch = '?tab=data'
const mapPath = `${overviewPath}/map/${planet}`
const regionSearch = `?world=${world}&planet=${planet}&branch=${branch}&window=24.1%2C121.45%2C150`

describe('workflow tutorial', () => {
  it('walks the local workflow through build, map, climate, refinement and backup', () => {
    const importStep: TutorialProgress = { flow: 'local', step: 'source' }
    const parameters = markMilestone(importStep, { type: 'imported', world })
    expect(parameters.step).toBe('parameters')
    expect(observeTutorialRoute(parameters, '/worlds/other', '?tab=parameters')).toBe(parameters)
    const build = observeTutorialRoute({ ...parameters, muted: true }, overviewPath, '?tab=parameters')
    expect(build).toMatchObject({ step: 'build', muted: false })
    expect(guideForRoute(build, overviewPath, '?tab=astronomy')).toMatchObject({
      active: false, to: `${overviewPath}?tab=parameters`, anchors: ['building', 'build'],
    })
    expect(markMilestone(build, { type: 'built', world, branch })).toBe(build)
    const map = markMilestone(build, { type: 'built', world })
    expect(map.step).toBe('map')
    expect(guideForRoute(map, overviewPath, '')).toMatchObject({ anchors: ['browserMap', 'map'], chapter: 2 })
    expect(observeTutorialRoute(map, mapPath, '?creation=1')).toBe(map)
    const monthly = observeTutorialRoute(map, mapPath, '?layer=temperature')
    expect(monthly).toMatchObject({ planet, step: 'monthly' })
    expect(guideForRoute(monthly, mapPath, '').anchors).toEqual(['monthly'])
    const climate = observeTutorialRoute(monthly, mapPath, '?layer=temperature&monthly=1')
    expect(climate.step).toBe('climate')
    expect(guideForRoute(climate, mapPath, '').anchors).toEqual(['lab'])
    expect(guideForRoute(climate, '/help', '')).toMatchObject({
      active: false, to: `${mapPath}?layer=temperature&trial=climate`,
    })
    expect(markMilestone(climate, { type: 'labOpened', world }).step).toBe('region')
    const region = markMilestone(climate, { type: 'forked', world, planet, base: null, branch })
    expect(region).toMatchObject({ step: 'region', branch })
    expect(guideForRoute(region, mapPath, '').anchors).toEqual(['regionOpen', 'regionForm', 'region'])
    expect(observeTutorialRoute(region, '/packs', regionSearch.replace(branch, 'other'))).toBe(region)
    const refine = observeTutorialRoute(region, '/packs', regionSearch)
    expect(refine).toMatchObject({ step: 'refine', region: regionSearch })
    expect(guideForRoute(refine, '/packs', regionSearch).anchors).toEqual([
      'regionResult', 'browserSave', 'refineRun', 'browserRefineRun', 'browserRefine', 'refine', 'regionTools',
    ])
    expect(guideForRoute(refine, '/help', '')).toMatchObject({ active: false, to: `/packs${regionSearch}` })
    expect(markMilestone(refine, { type: 'regionResult', world, planet, branch: null })).toBe(refine)
    const backup = markMilestone(refine, { type: 'regionResult', world, planet, branch })
    expect(backup.step).toBe('backup')
    expect(guideForRoute(backup, overviewPath, '')).toMatchObject({ active: true, anchors: ['snapshot'], chapter: 4 })
    expect(markMilestone(backup, { type: 'backup', world }).step).toBe('done')
  })

  it('walks the browser workflow through build, map, refinement and backup', () => {
    const importStep: TutorialProgress = { flow: 'browser', step: 'source' }
    const build = markMilestone(importStep, { type: 'imported', world })
    expect(build.step).toBe('build')
    expect(guideForRoute(build, overviewPath, '')).toMatchObject({ active: true, anchors: ['browserBuild'], chapter: 1 })
    expect(markMilestone(build, { type: 'built', world, branch })).toBe(build)
    const built = markMilestone(build, { type: 'built', world })
    expect(built.step).toBe('map')
    const monthly = observeTutorialRoute(built, mapPath, '')
    expect(monthly).toMatchObject({ step: 'monthly', planet })
    const climate = markMilestone(monthly, { type: 'monthly', world })
    expect(climate.step).toBe('climate')
    expect(markMilestone({ ...climate, step: 'monthly' }, { type: 'regionOpened', world }).step).toBe('region')
    const region = markMilestone(climate, { type: 'regionOpened', world })
    expect(region.step).toBe('region')
    // Browser region routes carry no branch; the progress branch is undefined.
    const browserRegion = `?world=${world}&planet=${planet}&window=24.1%2C121.45%2C150`
    const refine = observeTutorialRoute(region, '/packs', browserRegion)
    expect(refine).toMatchObject({ step: 'refine', region: browserRegion })
    expect(guideForRoute(refine, '/packs', browserRegion).anchors).toContain('browserSave')
    const backup = markMilestone(refine, { type: 'regionResult', world, planet, branch: null })
    expect(backup.step).toBe('backup')
    expect(guideForRoute(backup, overviewPath, dataSearch)).toMatchObject({
      active: true, anchors: ['browserBackup'], chapter: 4,
    })
    expect(guideForRoute(backup, overviewPath, '')).toMatchObject({ active: false, to: `${overviewPath}?tab=data` })
    expect(markMilestone(backup, { type: 'backup', world: 'other' })).toBe(backup)
    expect(markMilestone(backup, { type: 'backup', world }).step).toBe('done')
  })
})
