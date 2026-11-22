import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { isStaticMode } from '../api/mode'
import AtlasIcon from '../components/AtlasIcon'
import { guideForRoute, observeTutorialRoute, tutorialStartPath, useWorkflowTutorial, type TutorialProgress } from './tutorialProgress'
import './workflowTutorial.css'

export function TutorialEntry({ restart = false }: { restart?: boolean }) {
  const { t } = useTranslation('tutorial')
  const navigate = useNavigate()
  const continuing = useWorkflowTutorial(state => !!state.progress && state.progress.step !== 'done') && !restart
  const update = useWorkflowTutorial(state => state.update)
  return <button type="button" className="atlas-text-action workflow-guide-entry" onClick={() => {
    const current = useWorkflowTutorial.getState().progress
    if (continuing && current) {
      update(() => ({ ...current, muted: false }))
      navigate(guideForRoute(current, '', '').to)
    } else {
      update(() => ({ flow: isStaticMode() ? 'browser' : 'local', step: 'source' }))
      navigate(tutorialStartPath)
    }
  }}><AtlasIcon name="help" />{t(continuing ? 'resume' : restart ? 'restart' : 'start')}</button>
}

export default function WorkflowTutorial() {
  const progress = useWorkflowTutorial(state => state.progress)
  return progress ? <ActiveTutorial progress={progress} /> : null
}

function ActiveTutorial({ progress }: { progress: TutorialProgress }) {
  const { t } = useTranslation('tutorial')
  const { pathname, search } = useLocation()
  const update = useWorkflowTutorial(state => state.update)
  const guide = guideForRoute(progress, pathname, search)
  const panel = useRef<HTMLElement>(null)
  const target = useRef<HTMLElement | null>(null)
  const [layout, setLayout] = useState<{ name?: string; visible?: boolean; offscreen?: boolean; top?: number; left?: number }>({})
  const anchorKeys = guide.active && !progress.muted ? guide.anchors.join(' ') : ''

  useEffect(() => {
    update(current => current && observeTutorialRoute(current, pathname, search))
  }, [pathname, search, progress.step, update])

  useEffect(() => {
    const main = document.getElementById('main-content')
    const card = panel.current
    if (!card || !main || !anchorKeys) return
    const names = anchorKeys.split(' ')
    let frame = 0
    const measure = () => {
      frame = 0
      const candidates = [...main.querySelectorAll<HTMLElement>('[data-tutorial-anchor]')]
      const found = names.map(name => candidates.find(element => element.dataset.tutorialAnchor === name &&
        isRendered(element))).find(Boolean) ?? null
      const changed = target.current !== found
      if (changed) {
        target.current?.removeAttribute('data-tutorial-highlight')
        target.current = found
      }
      let rect = found?.getBoundingClientRect()
      if (changed && found && rect && !inView(found, rect)) {
        found.scrollIntoView({ behavior: 'instant', block: 'center', inline: 'nearest' })
        rect = found.getBoundingClientRect()
      }
      const visible = found && rect ? inView(found, rect) : false
      found?.toggleAttribute('data-tutorial-highlight', visible)
      const position = rect && visible ? positionGuide(rect, card.offsetWidth, card.offsetHeight) : { top: undefined, left: undefined }
      const next = { name: found?.dataset.tutorialAnchor, visible, offscreen: !!found && !visible, ...position }
      setLayout(previous => previous.name === next.name && previous.visible === next.visible &&
        previous.offscreen === next.offscreen && previous.top === next.top && previous.left === next.left ? previous : next)
    }
    const schedule = () => { if (!frame) frame = window.requestAnimationFrame(measure) }
    const observer = new MutationObserver(schedule)
    observer.observe(main, { childList: true, subtree: true, attributes: true,
      attributeFilter: ['data-tutorial-anchor', 'hidden', 'open', 'aria-expanded'] })
    const resize = new ResizeObserver(schedule)
    resize.observe(card)
    resize.observe(main)
    window.addEventListener('scroll', schedule, { capture: true, passive: true })
    window.addEventListener('resize', schedule)
    schedule()
    return () => {
      observer.disconnect()
      resize.disconnect()
      window.removeEventListener('scroll', schedule, true)
      window.removeEventListener('resize', schedule)
      window.cancelAnimationFrame(frame)
      target.current?.removeAttribute('data-tutorial-highlight')
      target.current = null
    }
  }, [anchorKeys, pathname])

  const toggle = () => update(current => current && { ...current, muted: !current.muted })
  const exit = () => update(() => null)
  if (progress.muted) return createPortal(<aside className="workflow-guide-dock" aria-label={t('label')}>
    <button type="button" className="atlas-tool-button" onClick={toggle}><AtlasIcon name="help" />{t('resume')}</button>
  </aside>, document.body)

  const name = anchorKeys && guide.anchors.find(anchor => anchor === layout.name) || progress.step
  const message = progress.flow === 'browser' && name === 'configure' ? 'configureBrowser'
    : progress.flow === 'browser' && name === 'build' ? 'browserBuild'
      : progress.flow === 'browser' && name === 'backup' ? 'browserBackup'
        : progress.flow === 'browser' && name === 'refine' ? 'browserRefineRun' : name
  const done = progress.step === 'done'
  const anchored = !!anchorKeys && layout.visible && name === layout.name
  return createPortal(<aside ref={panel} aria-label={t('label')} className="workflow-guide"
    style={anchored ? { left: layout.left, top: layout.top, right: 'auto', bottom: 'auto' } : undefined}>
    <div className="workflow-guide-heading">
      <strong>{t(done ? 'complete' : `chapters.${progress.flow}.${guide.chapter}`)}</strong>
      {!done && <span>{t('chapterCount', { chapter: guide.chapter, total: 4 })}</span>}
    </div>
    <p aria-live="polite" aria-atomic="true">{t(guide.active ? `hint.${message}` : `return.${progress.step === 'backup' ? 'backup' : 'default'}`)}</p>
    <div className="workflow-guide-actions">
      {!guide.active && <Link className="workflow-guide-action" to={guide.to}>{t(progress.step === 'backup'
        ? progress.flow === 'browser' ? 'openData' : 'openOverview' : 'openStep')}</Link>}
      {!!anchorKeys && layout.offscreen && name === layout.name && <button type="button" className="workflow-guide-action"
        onClick={() => locateTarget(target.current)}>{t('locate')}</button>}
      {!done && <button type="button" onClick={toggle}>{t('skipHint')}</button>}
      <button type="button" onClick={exit}>{t(done ? 'close' : 'exit')}</button>
    </div>
  </aside>, document.body)
}

function locateTarget(element: HTMLElement | null) {
  if (!element) return
  element.scrollIntoView({ block: 'center', inline: 'nearest' })
  const selector = 'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), summary'
  const control = element.matches(selector) ? element : element.querySelector<HTMLElement>(selector)
  control?.focus({ preventScroll: true })
}

function isRendered(element: HTMLElement) {
  if (!element.getClientRects().length || element.closest('[hidden]')) return false
  for (let details = element.closest('details:not([open])'); details;
    details = details.parentElement?.closest('details:not([open])') ?? null) {
    if (!details.querySelector(':scope > summary')?.contains(element)) return false
  }
  return true
}

function inView(element: HTMLElement, rect: DOMRect) {
  const x = (rect.left + rect.right) / 2
  const y = (rect.top + rect.bottom) / 2
  if (x <= 0 || x >= document.documentElement.clientWidth || y <= 0 || y >= window.innerHeight) return false
  for (let parent = element.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
    const style = window.getComputedStyle(parent)
    if (style.overflowX === 'visible' && style.overflowY === 'visible') continue
    const bounds = parent.getBoundingClientRect()
    if (style.overflowX !== 'visible' && (x < bounds.left || x > bounds.right)) return false
    if (style.overflowY !== 'visible' && (y < bounds.top || y > bounds.bottom)) return false
  }
  return true
}

function positionGuide(rect: DOMRect, width: number, height: number) {
  const viewport = document.documentElement.clientWidth
  const edge = 12
  const gap = 14
  const bounded = (value: number, available: number) => Math.round(Math.max(edge, Math.min(value, available - edge)))
  if (viewport >= 768 && rect.left - gap - width >= viewport / 4) {
    return { left: bounded(rect.left - gap - width, viewport - width), top: bounded(rect.top, window.innerHeight - height) }
  }
  if (viewport >= 768 && rect.right + gap + width <= viewport - edge) {
    return { left: bounded(rect.right + gap, viewport - width), top: bounded(rect.top, window.innerHeight - height) }
  }
  const roomBelow = window.innerHeight - rect.bottom - edge
  const roomAbove = rect.top - edge
  const top = roomBelow >= height + gap || roomBelow > roomAbove ? rect.bottom + gap : rect.top - gap - height
  return { left: bounded(rect.left, viewport - width), top: bounded(top, window.innerHeight - height) }
}
