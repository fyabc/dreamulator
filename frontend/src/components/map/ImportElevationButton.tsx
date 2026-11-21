/**
 * ImportElevationButton — opens the import panel for the map being viewed.
 *
 * The panel previews the file through the backend and writes only when the
 * author confirms; cancelling closes it without touching the world.  Hidden
 * write action in static mode.
 */

import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { api } from '../../api/client'
import { isStaticMode } from '../../api/mode'
import type { ElevationImportResponse } from '../../api/elevationImport'
import ElevationImportPanel from '../import/ElevationImportPanel'

export type ImportElevationResult = ElevationImportResponse

interface Props {
  worldName: string
  planetId: string
  branch: string | null
  onImported: (result: ImportElevationResult) => void
}

export default function ImportElevationButton({ worldName, planetId, branch, onImported }: Props) {
  const { t } = useTranslation('map')
  const { t: ti } = useTranslation('importer')
  const [open, setOpen] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const dialogHeading = useRef<HTMLHeadingElement>(null)
  const staticMode = isStaticMode()

  useEffect(() => {
    if (!open) return
    dialogHeading.current?.focus({ preventScroll: true })
    const button = trigger.current
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      button?.focus({ preventScroll: true })
    }
  }, [open])

  return (
    <>
      <button
        ref={trigger}
        type="button"
        aria-haspopup="dialog"
        onClick={() => setOpen(true)}
        disabled={staticMode}
        title={staticMode ? t('hint.staticReadonly') : t('hint.importHeightmapTitle')}
        className="px-3 py-1 text-sm rounded-lg bg-space-surface text-gray-300 hover:text-neon-cyan border border-space-border hover:border-neon-cyan/30 transition-colors disabled:opacity-40"
      >
        {t('action.importHeightmap')}
      </button>
      {open && createPortal(
        <div className="atlas-shell fixed inset-0 z-50 overflow-y-auto bg-black/70 text-gray-100" role="dialog"
          aria-modal="true" aria-label={ti('modalTitle')}>
          <div className="max-w-6xl mx-auto my-6 px-4">
            <div className="glass-panel flex items-center flex-wrap gap-x-3 px-4 py-3 mb-3">
              <h2 ref={dialogHeading} tabIndex={-1} className="text-lg font-semibold text-neon-cyan">{ti('modalTitle')}</h2>
              <span className="text-xs text-gray-400">
                {ti('modalTarget', { world: worldName, planet: planetId, branch: branch ?? ti('target.rootBranch') })}
              </span>
            </div>
            <ElevationImportPanel
              target={{ world: worldName, planetId, branch }}
              onCancel={() => setOpen(false)}
              onConfirm={async (file, mapping, notes) => {
                const result = await api.importElevation(worldName, planetId, file, branch, mapping, notes || undefined)
                setOpen(false)
                onImported(result)
                return result
              }}
            />
          </div>
        </div>, document.body,
      )}
    </>
  )
}
