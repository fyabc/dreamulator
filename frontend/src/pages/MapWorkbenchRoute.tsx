import { lazy, useCallback, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useQuery } from '@tanstack/react-query'
import { Outlet, useMatch, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api } from '../api/client'
import { MapTemperatureTrial, trialButtonId } from '../components/map/MapTemperatureTrial'
import type { TemperatureOrigin } from '../playground/temperatureDraft'
import { useTemperatureTrialPreview, type MapTemperatureTrialSession } from '../viewers/map/useTemperatureTrialPreview'

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
  return <TemperatureTrialSession world={worldName} planet={planetId} branch={branch}
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
  const [panelHost] = useState(() => document.createElement('div'))
  const scope = world && planet ? JSON.stringify([world, planet, branch, revision]) : null
  const input = useMemo(() => {
    const params = new URLSearchParams({ world: world ?? '', planet: planet ?? '' })
    if (branch) params.set('branch', branch)
    if (draft) params.set('draft', draft)
    return params
  }, [world, planet, branch, draft])
  const trial = useTemperatureTrialPreview(scope)
  const attachPanel = useCallback((slot: HTMLDivElement | null) => {
    if (slot) slot.append(panelHost)
    else panelHost.remove()
  }, [panelHost])
  const openPanel = () => {
    setVisited(true)
    setOpen(true)
  }
  const closePanel = () => {
    setOpen(false)
    document.getElementById(trialButtonId)?.focus()
  }
  const session: MapTemperatureTrialSession = {
    ...trial, open: open && !clean, openPanel, closePanel, attachPanel,
    replaceElevation: () => { if (!draft) setRevision(revision => revision + 1) },
  }
  return <>
    <Outlet context={session} />
    {scope && visited && createPortal(<MapTemperatureTrial search={input}
      open={session.open} onClose={closePanel} onPreview={trial.report} onShow={trial.show} showing={trial.preview !== null} />,
    panelHost, scope)}
  </>
}
