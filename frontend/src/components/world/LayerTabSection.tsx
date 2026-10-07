import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

/**
 * Unified layout for a world-detail layer tab.
 *
 * Authored setting documents are the primary content (rendered first,
 * unfolded); engine-derived data cards come after them inside a collapsible
 * section, collapsed by default so the authored canon reads as the main
 * body. The expand/collapse choice is remembered per world + tab in
 * localStorage (best-effort; privacy mode failures are ignored).
 */

function readStoredOpen(worldName: string, tab: string): boolean {
  try {
    return localStorage.getItem(`wd-derived-open-${worldName}-${tab}`) === 'true'
  } catch {
    return false
  }
}

function storeOpen(worldName: string, tab: string, open: boolean) {
  try {
    localStorage.setItem(`wd-derived-open-${worldName}-${tab}`, open ? 'true' : 'false')
  } catch {
    // Private-browsing storage failures are non-fatal — fall back to
    // per-visit default (collapsed).
  }
}

export default function LayerTabSection({
  worldName,
  tab,
  derived,
  documents,
}: {
  worldName: string
  tab: string
  /** Engine-derived data cards (catalog, dump, preview, …). May be null. */
  derived: ReactNode
  /** Authored setting documents (LayerDocuments) — the primary content. */
  documents: ReactNode
}) {
  const { t } = useTranslation('worlds')
  const [derivedOpen, setDerivedOpen] = useState(() => readStoredOpen(worldName, tab))

  const toggle = () => {
    setDerivedOpen((prev) => {
      storeOpen(worldName, tab, !prev)
      return !prev
    })
  }

  return (
    <div className="space-y-6">
      {documents}
      {derived != null && (
        <div className="glass-panel p-4 sm:p-6">
          <button
            type="button"
            onClick={toggle}
            className="flex items-center gap-2 w-full text-left group"
            aria-expanded={derivedOpen}
          >
            <span
              className={`text-gray-400 group-hover:text-neon-cyan transition-transform duration-200 ${
                derivedOpen ? 'rotate-90' : ''
              }`}
            >
              ▸
            </span>
            <span className="text-sm font-semibold text-gray-400 uppercase tracking-wide group-hover:text-gray-200 transition-colors">
              {t('detail.derivedData')}
            </span>
            <span className="text-xs text-gray-600 normal-case tracking-normal">
              {t('detail.derivedDataHint')}
            </span>
          </button>
          {derivedOpen && (
            <div className="mt-4">
              {derived}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
