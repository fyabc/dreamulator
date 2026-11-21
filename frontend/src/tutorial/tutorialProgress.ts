import { create } from 'zustand'
import { isStaticMode } from '../api/mode'

export const tutorialStartPath = '/new-world?start=heightmap'
const storageKey = `dreamulator-workflow-tutorial-v1:${isStaticMode() ? 'browser' : 'local'}`
const steps = ['source', 'parameters', 'build', 'map', 'monthly', 'climate', 'region', 'refine', 'backup',
  'browserMap', 'browserView', 'browserBackup', 'done'] as const

type Step = typeof steps[number]
type Flow = 'local' | 'browser'
export type TutorialProgress = {
  flow: Flow
  step: Step
  world?: string
  planet?: string
  branch?: string
  region?: string
  muted?: boolean
}

type Milestone =
  | { type: 'imported'; world: string }
  | { type: 'built' | 'backup'; world: string; branch?: string | null }
  | { type: 'forked'; world: string; planet: string; base: string | null; branch: string }
  | { type: 'regionResult'; world: string; planet: string; branch: string | null }

export function markMilestone(progress: TutorialProgress, event: Milestone): TutorialProgress {
  if (event.type === 'imported') {
    return progress.step === 'source' ? { flow: progress.flow, world: event.world,
      step: progress.flow === 'browser' ? 'browserMap' : 'parameters' } : progress
  }
  if (event.world !== progress.world) return progress
  if (event.type === 'built' && !event.branch && (progress.step === 'parameters' || progress.step === 'build')) {
    return { ...progress, step: 'map', muted: false }
  }
  if (event.type === 'forked' && progress.step === 'climate' && !event.base && event.planet === progress.planet) {
    return { ...progress, step: 'region', branch: event.branch, muted: false }
  }
  if (event.type === 'regionResult' && progress.step === 'refine' &&
    event.planet === progress.planet && event.branch === progress.branch) {
    return { ...progress, step: 'backup', muted: false }
  }
  if (event.type === 'backup' && (progress.step === 'backup' || progress.step === 'browserBackup')) {
    return { ...progress, step: 'done', muted: false }
  }
  return progress
}

function scope(progress: TutorialProgress, pathname: string, search: string) {
  const query = new URLSearchParams(search)
  const world = `/worlds/${encodeURIComponent(progress.world ?? '')}`
  const parts = pathname.split('/')
  const map = !!progress.world && parts.length === 5 && `/${parts[1]}/${parts[2]}` === world &&
    (parts[3] === 'map' || parts[3] === 'globe') && !!parts[4]
  const creation = query.get('creation') === '1'
  const branch = query.get('branch')
  const region = pathname === '/packs' && query.get('world') === progress.world &&
    query.get('planet') === progress.planet && branch === progress.branch && !!query.get('window')
  return { query, detail: !!progress.world && pathname === world, map: map && !creation, creation: map && creation,
    region, branch, planet: map ? parts[4] : undefined }
}

export function observeTutorialRoute(progress: TutorialProgress, pathname: string, search: string): TutorialProgress {
  const route = scope(progress, pathname, search)
  if (progress.step === 'parameters' && route.detail && !route.branch && route.query.get('tab') === 'parameters') {
    return { ...progress, step: 'build', muted: false }
  }
  if (progress.step === 'map' && route.map && !route.branch && route.planet) {
    return { ...progress, step: route.query.get('monthly') === '1' ? 'climate' : 'monthly', planet: route.planet, muted: false }
  }
  if (progress.step === 'monthly' && route.map && !route.branch && route.planet === progress.planet && route.query.get('monthly') === '1') {
    return { ...progress, step: 'climate', muted: false }
  }
  if ((progress.step === 'region' || progress.step === 'refine') && route.region && !route.query.has('pack') && progress.region !== search) {
    return { ...progress, step: 'refine', region: search, muted: progress.step === 'refine' && progress.muted }
  }
  if (progress.step === 'browserMap' && route.creation) {
    return { ...progress, step: 'browserView', muted: false }
  }
  if (progress.step === 'browserView' && route.detail && route.query.get('tab') === 'data') {
    return { ...progress, step: 'browserBackup', muted: false }
  }
  return progress
}

export function guideForRoute(progress: TutorialProgress, pathname: string, search: string) {
  const route = scope(progress, pathname, search)
  const world = `/worlds/${encodeURIComponent(progress.world ?? '')}`
  const map = `${world}/map/${progress.planet ?? 'planet_terra'}`
  const mapParams = new URLSearchParams({ layer: 'temperature' })
  if (progress.branch) mapParams.set('branch', progress.branch)
  if (progress.step === 'climate') mapParams.set('trial', 'climate')
  const officialMap = `${map}?${mapParams}`
  const data = `${world}?tab=data`
  const tutorialMap = route.map && route.planet === progress.planet && route.branch === (progress.branch ?? null)

  switch (progress.step) {
    case 'source': return { active: pathname === '/new-world' && route.query.get('start') === 'heightmap', to: tutorialStartPath,
      anchors: ['configure', 'upload'], chapter: 1 }
    case 'parameters': return { active: route.detail && !route.branch, to: data, anchors: ['parameters'], chapter: 1 }
    case 'build': return { active: route.detail && !route.branch, to: `${world}?tab=parameters`, anchors: ['building', 'build'], chapter: 1 }
    case 'map': return { active: route.detail && !route.branch, to: `${world}?tab=parameters`, anchors: ['map'], chapter: 2 }
    case 'monthly': return { active: tutorialMap, to: officialMap, anchors: ['monthly'], chapter: 2 }
    case 'climate': return { active: tutorialMap, to: officialMap, anchors: ['trialBranch', 'trialWait', 'trialRun', 'lab'], chapter: 2 }
    case 'region': return { active: tutorialMap, to: officialMap, anchors: ['regionOpen', 'regionForm', 'region'], chapter: 3 }
    case 'refine': return { active: route.region && !route.query.has('pack'), to: `/packs${progress.region ?? ''}`,
      anchors: ['regionResult', 'refining', 'refineRun', 'refine'], chapter: 3 }
    case 'backup': return { active: route.detail, to: world, anchors: ['snapshot'], chapter: 4 }
    case 'browserMap': return { active: route.detail && route.query.get('tab') === 'data', to: data, anchors: ['browserMap'], chapter: 2 }
    case 'browserView': return { active: route.creation, to: `${map}?creation=1`, anchors: ['browserView'], chapter: 2 }
    case 'browserBackup': return { active: route.detail && route.query.get('tab') === 'data', to: data, anchors: ['browserBackup'], chapter: 2 }
    case 'done': return { active: true, to: world, anchors: [], chapter: progress.flow === 'browser' ? 2 : 4 }
  }
}

function readProgress(): TutorialProgress | null {
  try {
    const saved = JSON.parse(sessionStorage.getItem(storageKey) ?? 'null') as TutorialProgress | null
    if (!saved || !['local', 'browser'].includes(saved.flow) || !steps.includes(saved.step)) return null
    const isId = (value: unknown) => typeof value === 'string' && /^[a-zA-Z0-9_-]+$/.test(value)
    if (saved.step !== 'source' && !isId(saved.world)) return null
    if (saved.planet !== undefined && !isId(saved.planet)) return null
    if (saved.branch !== undefined && !isId(saved.branch)) return null
    if (saved.region !== undefined && (typeof saved.region !== 'string' || !saved.region.startsWith('?'))) return null
    return saved
  } catch { return null }
}

type TutorialStore = {
  progress: TutorialProgress | null
  update: (change: (progress: TutorialProgress | null) => TutorialProgress | null) => void
}

function saveProgress(progress: TutorialProgress | null) {
  try {
    if (progress) sessionStorage.setItem(storageKey, JSON.stringify(progress))
    else sessionStorage.removeItem(storageKey)
  } catch { return }
}

export const useWorkflowTutorial = create<TutorialStore>((set, get) => ({
  progress: readProgress(),
  update: change => {
    const current = get().progress
    const next = change(current)
    if (next === current) return
    saveProgress(next)
    set({ progress: next })
  },
}))

export function tutorialMilestone(event: Milestone) {
  useWorkflowTutorial.getState().update(current => current && markMilestone(current, event))
}
