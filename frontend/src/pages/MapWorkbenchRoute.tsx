import { lazy, useCallback, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useQuery } from '@tanstack/react-query'
import { Outlet, useMatch, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api } from '../api/client'
import { MapTemperatureTrial, trialButtonId } from '../components/map/MapTemperatureTrial'
import { initialLayerState } from '../components/map/layerStateInit'
import type { TemperatureOrigin } from '../playground/temperatureDraft'
import { useTemperatureTrialPreview, type MapMode, type MapTemperatureTrialSession } from '../viewers/map/useTemperatureTrialPreview'

const TemperatureLab = lazy(() => import('../playground/TemperatureLab'))

export default function MapWorkbenchRoute() {
  const match = useMatch('/worlds/:worldName/:view/:planetId?')
  const { worldName, view, planetId } = match?.params ?? {}
  const [search] = useSearchParams()
  if (view === 'map' && planetId && search.get('creation') === '1') return <Outlet />
  const branch = search.get('branch') || null
  const draft = search.get('draft')
  const clean = search.get('clean') === '1'
  if (worldName && planetId && draft) {
    return <DraftWorkbench key={JSON.stringify([worldName, planetId, branch, draft])}
      world={worldName} planet={planetId} branch={branch} draft={draft} clean={clean} />
  }
  return <TemperatureTrialSession key={JSON.stringify([worldName, planetId, branch])}
    world={worldName} planet={planetId} branch={branch}
    clean={clean} initiallyOpen={search.get('trial') === 'climate'} />
}

function DraftWorkbench({ world, planet, branch, draft, clean }: TemperatureOrigin & { draft: string; clean: boolean }) {
  const { t } = useTranslation('playground')
  const maps = useQuery({ queryKey: ['mapPlanets', world, branch],
    queryFn: () => api.listMapPlanets(world, branch), retry: false })
  const mapped = maps.data?.includes(planet) ?? false
  const meta = useQuery({ queryKey: ['mapMeta', world, planet, branch],
    queryFn: () => api.getMapMeta(world, planet, branch), enabled: mapped, retry: false })
  const elevation = useQuery({ queryKey: ['elevationBlob', world, planet, branch],
    queryFn: () => api.getElevationBlob(world, planet, branch), enabled: mapped, retry: false })

  if ((!maps.isPending && !mapped) || meta.isError || elevation.isError) {
    const input = new URLSearchParams({ world, planet, draft })
    if (branch) input.set('branch', branch)
    return <TemperatureLab search={input} recovery />
  }
  if (!meta.data || !elevation.data) {
    return <p role="status" className="p-6 text-sm text-gray-300">{t('action.loadingInput')}</p>
  }
  return <TemperatureTrialSession world={world} planet={planet} branch={branch} draft={draft} clean={clean} initiallyOpen />
}

function TemperatureTrialSession({ world, planet, branch, draft, clean, initiallyOpen }: {
  world?: string
  planet?: string
  branch: string | null
  draft?: string
  clean: boolean
  initiallyOpen: boolean
}) {
  const [open, setOpen] = useState(initiallyOpen)
  const [visited, setVisited] = useState(initiallyOpen)
  const [revision, setRevision] = useState(0)
  const [modeSelection, setModeSelection] = useState<{ scope: string | null; mode: MapMode } | null>(null)
  const [layerState, setLayerState] = useState(() => trialLayerState(null))
  const [panelHost] = useState(() => document.createElement('div'))
  const panelTrigger = useRef<HTMLElement | null>(null)
  const scope = world && planet ? JSON.stringify([world, planet, branch, revision]) : null
  const mode = modeSelection?.scope === scope ? modeSelection.mode : 'official'
  const input = useMemo(() => {
    const params = new URLSearchParams({ world: world ?? '', planet: planet ?? '' })
    if (branch) params.set('branch', branch)
    if (draft) params.set('draft', draft)
    return params
  }, [world, planet, branch, draft])
  const trial = useTemperatureTrialPreview(scope, mode)
  const showTrial = useCallback(() => {
    setLayerState(trialLayerState('temperature'))
    setModeSelection({ scope, mode: 'trial' })
  }, [scope])
  const attachPanel = useCallback((slot: HTMLDivElement | null) => {
    if (slot) slot.append(panelHost)
    else panelHost.remove()
  }, [panelHost])
  const openPanel = () => {
    panelTrigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    setVisited(true)
    setOpen(true)
  }
  const closePanel = () => {
    setOpen(false)
    const trigger = panelTrigger.current
    if (trigger && trigger !== document.body && trigger.isConnected) trigger.focus({ preventScroll: true })
    else document.getElementById(trialButtonId)?.focus({ preventScroll: true })
  }
  const session: MapTemperatureTrialSession = {
    ...trial, mode, layerState, setLayerState, open: open && !clean, openPanel, closePanel, attachPanel,
    selectMode: (next) => {
      setModeSelection({ scope, mode: next })
      if (next === 'trial' && !trial.available) openPanel()
      if (next === 'official') setOpen(false)
    },
    replaceElevation: () => {
      if (draft) return
      setLayerState(trialLayerState(null))
      setRevision(revision => revision + 1)
    },
  }
  return <>
    <Outlet context={session} />
    {scope && visited && createPortal(<MapTemperatureTrial search={input}
      open={session.open} onClose={closePanel} onPreview={trial.report} onShow={showTrial} />,
    panelHost, scope)}
  </>
}

function trialLayerState(layer: 'temperature' | null) {
  const state = initialLayerState(layer, false)
  state.layers.coastlines = 0
  return state
}
