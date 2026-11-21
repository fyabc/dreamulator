import { useCallback, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { Outlet, useMatch, useSearchParams } from 'react-router-dom'
import { MapTemperatureTrial, trialButtonId } from '../components/map/MapTemperatureTrial'
import { useTemperatureTrialPreview, type MapTemperatureTrialSession } from '../viewers/map/useTemperatureTrialPreview'

export default function MapWorkbenchRoute() {
  const match = useMatch('/worlds/:worldName/:view/:planetId?')
  const { worldName, view, planetId } = match?.params ?? {}
  const [search] = useSearchParams()
  if (view === 'map' && planetId && search.get('creation') === '1') return <Outlet />
  return <TemperatureTrialSession world={worldName} planet={planetId} branch={search.get('branch') || null}
    clean={search.get('clean') === '1'} initiallyOpen={search.get('trial') === 'climate'} />
}

function TemperatureTrialSession({ world, planet, branch, clean, initiallyOpen }: {
  world?: string
  planet?: string
  branch: string | null
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
    return params
  }, [world, planet, branch])
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
    replaceElevation: () => setRevision(revision => revision + 1),
  }
  return <>
    <Outlet context={session} />
    {scope && visited && createPortal(<MapTemperatureTrial search={input}
      open={session.open} onClose={closePanel} onPreview={trial.report} onShow={trial.show} showing={trial.preview !== null} />,
    panelHost, scope)}
  </>
}
