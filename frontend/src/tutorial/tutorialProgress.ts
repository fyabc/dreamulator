import { create } from 'zustand'
import { isStaticMode } from '../api/mode'

export const tutorialStartPath = '/new-world?start=heightmap'
const storageKey = `dreamulator-workflow-tutorial-v2:${isStaticMode() ? 'browser' : 'local'}`
const steps = ['source', 'parameters', 'build', 'map', 'monthly', 'climate', 'region', 'refine', 'backup',
  'done'] as const

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
  | { type: 'monthly' | 'labOpened' | 'regionOpened'; world: string }
  | { type: 'regionResult'; world: string; planet: string; branch: string | null }

const sameBranch = (left: string | null | undefined, right: string | null | undefined) =>
  (left ?? null) === (right ?? null)

export function markMilestone(progress: TutorialProgress, event: Milestone): TutorialProgress {
  if (event.type === 'imported') {
    return progress.step === 'source' ? { flow: progress.flow, world: event.world,
      step: progress.flow === 'browser' ? 'build' : 'parameters' } : progress
  }
  if (event.world !== progress.world) return progress
  if (event.type === 'built' && !event.branch && (progress.step === 'parameters' || progress.step === 'build')) {
    return { ...progress, step: 'map', muted: false }
  }
  if (event.type === 'monthly' && progress.step === 'monthly') {
    return { ...progress, step: 'climate', muted: false }
  }
  if (event.type === 'labOpened' && progress.step === 'climate') {
    return { ...progress, step: 'region', muted: false }
  }
  if (event.type === 'regionOpened' && (progress.step === 'monthly' || progress.step === 'climate')) {
    return { ...progress, step: 'region', muted: false }
  }
  if (event.type === 'forked' && progress.step === 'climate' && !event.base && event.planet === progress.planet) {
    return { ...progress, step: 'region', branch: event.branch, muted: false }
  }
  if (event.type === 'regionResult' && progress.step === 'refine' &&
    event.planet === progress.planet && sameBranch(event.branch, progress.branch)) {
    return { ...progress, step: 'backup', muted: false }
  }
  if (event.type === 'backup' && progress.step === 'backup') {
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
  const planet = map ? parts[4] : null
  const region = pathname === '/packs' && query.get('world') === progress.world &&
    (!progress.planet || query.get('planet') === progress.planet) &&
    sameBranch(branch, progress.branch) && !!query.get('window')
  return { query, detail: !!progress.world && pathname === world, map: map && !creation, creation: map && creation,
    region, branch, planet }
}

export function observeTutorialRoute(progress: TutorialProgress, pathname: string, search: string): TutorialProgress {
  const route = scope(progress, pathname, search)
  if (progress.step === 'parameters' && route.detail && !route.branch && route.query.get('tab') === 'parameters') {
    return { ...progress, step: 'build', muted: false }
  }
  if (progress.step === 'build' && route.map && !route.branch && route.planet) {
    return { ...progress, step: 'map', planet: route.planet, muted: false }
  }
  if (progress.step === 'map' && route.map && route.planet) {
    return { ...progress, step: route.query.get('monthly') === '1' ? 'climate' : 'monthly',
      planet: route.planet, branch: route.branch ?? undefined, muted: false }
  }
  if (progress.step === 'monthly' && route.map && !route.branch && route.planet === progress.planet &&
    route.query.get('monthly') === '1') {
    return { ...progress, step: 'climate', muted: false }
  }
  if ((progress.step === 'monthly' || progress.step === 'climate' || progress.step === 'region') &&
    route.region && !route.query.has('pack') && progress.region !== search) {
    return { ...progress, step: 'refine', region: search, muted: false }
  }
  return progress
}

export function guideForRoute(progress: TutorialProgress, pathname: string, search: string) {
  const route = scope(progress, pathname, search)
  const browser = progress.flow === 'browser'
  const world = `/worlds/${encodeURIComponent(progress.world ?? '')}`
  const map = `${world}/map/${progress.planet ?? 'planet_terra'}`
  const mapParams = new URLSearchParams({ layer: 'temperature' })
  if (progress.branch) mapParams.set('branch', progress.branch)
  if (progress.step === 'climate') mapParams.set('trial', 'climate')
  const officialMap = `${map}?${mapParams}`
  const stepMap = browser ? map : officialMap
  const data = `${world}?tab=data`
  const tutorialMap = (route.map || route.creation) && route.planet === progress.planet &&
    sameBranch(route.branch, progress.branch)
  const tab = route.query.get('tab')
  const buildVisible = route.detail && (!tab || tab === 'overview' || tab === 'parameters')

  switch (progress.step) {
    case 'source': return { active: pathname === '/new-world' && route.query.get('start') === 'heightmap', to: tutorialStartPath,
      anchors: ['configure', 'upload'], chapter: 1 }
    case 'parameters': return { active: route.detail && !route.branch, to: data, anchors: ['parameters'], chapter: 1 }
    case 'build': return browser
      ? { active: route.detail && !route.branch, to: world, anchors: ['browserBuild'], chapter: 1 }
      : { active: buildVisible && !route.branch, to: `${world}?tab=parameters`, anchors: ['building', 'build'], chapter: 1 }
    case 'map': return { active: route.detail && !route.branch, to: world, anchors: ['browserMap', 'map'], chapter: 2 }
    case 'monthly': return { active: tutorialMap, to: stepMap, anchors: ['monthly'], chapter: 2 }
    case 'climate': return { active: tutorialMap, to: stepMap, anchors: ['lab'], chapter: 2 }
    case 'region': return { active: tutorialMap, to: stepMap, anchors: ['regionOpen', 'regionForm', 'region'], chapter: 3 }
    case 'refine': return { active: route.region && !route.query.has('pack'), to: `/packs${progress.region ?? ''}`,
      anchors: ['regionResult', 'browserSave', 'refineRun', 'browserRefineRun', 'browserRefine', 'refine', 'regionTools'], chapter: 3 }
    case 'backup': return browser
      ? { active: route.detail && tab === 'data', to: data, anchors: ['browserBackup'], chapter: 4 }
      : { active: buildVisible, to: world, anchors: ['snapshot'], chapter: 4 }
    case 'done': return { active: true, to: world, anchors: [], chapter: 4 }
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
