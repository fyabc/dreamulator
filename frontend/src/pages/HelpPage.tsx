/**
 * HelpPage — GitBook/wiki-style help system.
 *
 * Sidebar navigation with collapsible sections + content area.  The URL hash
 * (e.g. `/help#map-controls`) drives which section is open and scrolls to it.
 * Other pages link here with target="_blank" so users can reference help
 * while keeping their map / world view open.
 *
 * All help content lives in the shared helpContent.ts module — the single
 * source of truth used by layer panels, tooltips, and this page.
 */

import { useEffect, useRef, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation } from 'react-router-dom'
import { HELP_SECTIONS, type HelpSection } from '../components/map/helpContent'

/** Simple markdown-like renderer for inline formatting. */
function renderContent(text: string) {
  // Split into paragraphs
  return text.split('\n\n').map((block, i) => {
    const trimmed = block.trim()
    if (!trimmed) return null

    // Code blocks
    if (trimmed.startsWith('```')) {
      const lines = trimmed.split('\n')
      const code = lines.slice(1, -1).join('\n')
      return (
        <pre key={i} className="bg-black/30 rounded-lg p-3 my-2 overflow-x-auto">
          <code className="text-xs text-gray-300 font-mono whitespace-pre-wrap">{code}</code>
        </pre>
      )
    }

    // Inline code
    const rendered = trimmed.replace(/`([^`]+)`/g, (_m, code: string) =>
      `<code class="bg-space-surface px-1 py-0.5 rounded text-xs text-neon-cyan/80 font-mono">${code}</code>`,
    )

    // Bold
    const withBold = rendered.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')

    // List items starting with -
    if (trimmed.startsWith('- ')) {
      const items = trimmed.split('\n').filter((l) => l.startsWith('- '))
      return (
        <ul key={i} className="space-y-1 my-1">
          {items.map((item, j) => (
            <li
              key={j}
              className="text-sm text-gray-400 flex gap-2"
              dangerouslySetInnerHTML={{ __html: item.slice(2).replace(/`([^`]+)`/g, '<code class="bg-space-surface px-1 py-0.5 rounded text-xs text-neon-cyan/80 font-mono">$1</code>').replace(/\*\*([^*]+)\*\*/g, '<strong class="text-gray-200">$1</strong>') }}
            />
          ))}
        </ul>
      )
    }

    // Convert single \n → <br/> for inline line breaks
    const withBreaks = withBold.replace(/\n/g, '<br/>')

    return (
      <p
        key={i}
        className="text-sm text-gray-400 leading-relaxed mb-2"
        dangerouslySetInnerHTML={{ __html: withBreaks }}
      />
    )
  })
}

function SectionContent({ section }: { section: HelpSection }) {
  const { t } = useTranslation('help')
  const entries = useMemo(() => section.render(t), [section, t])

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-neon-cyan neon-glow-subtle">
        {section.icon} {t(section.title)}
      </h2>
      {entries.map((entry, i) => (
        <div key={i} className="glass-panel p-4">
          <h3 className="text-base font-semibold text-gray-200 mb-2">
            {entry.title}
          </h3>
          {renderContent(entry.content)}
        </div>
      ))}
    </div>
  )
}

export default function HelpPage() {
  const { t } = useTranslation('common')
  const location = useLocation()
  const sectionRefs = useRef<Map<string, HTMLDivElement>>(new Map())

  // Current section from URL hash
  const activeSection = location.hash?.slice(1) || HELP_SECTIONS[0].id

  // Scroll to section when hash changes
  useEffect(() => {
    const el = sectionRefs.current.get(activeSection)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [activeSection])

  return (
    <div className="flex h-[calc(100vh-56px)]">
      {/* Sidebar */}
      <nav className="w-56 shrink-0 bg-space-panel/50 border-r border-space-border overflow-y-auto p-3">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3 px-2">
          {t('help.toc')}
        </h2>
        <ul className="space-y-0.5">
          {HELP_SECTIONS.map((s) => {
            const isActive = s.id === activeSection
            return (
              <li key={s.id}>
                <a
                  href={`#${s.id}`}
                  className={`flex items-center gap-2 px-2 py-1.5 rounded-lg text-sm transition-colors ${
                    isActive
                      ? 'bg-neon-cyan/10 text-neon-cyan border border-neon-cyan/20'
                      : 'text-gray-400 hover:bg-space-surface hover:text-gray-200 border border-transparent'
                  }`}
                >
                  <span className="text-base flex-shrink-0">{s.icon}</span>
                  <span className="truncate">{t(s.title)}</span>
                </a>
              </li>
            )
          })}
        </ul>
      </nav>

      {/* Content */}
      <main className="flex-1 overflow-y-auto p-6">
        <div className="max-w-3xl space-y-16">
          {HELP_SECTIONS.map((s) => (
            <div
              key={s.id}
              ref={(el) => {
                if (el) sectionRefs.current.set(s.id, el)
              }}
              id={s.id}
            >
              <SectionContent section={s} />
            </div>
          ))}
        </div>

        {/* Footer */}
        <p className="mt-12 text-xs text-gray-600 text-center">
          {t('help.footerDocs')} <code className="text-gray-500">docs/</code>{' '}
          {t('help.footerDocsSuffix')}{' '}
          {t('help.footerCli')} <code className="text-gray-500">dreamulator --help</code>
          {t('help.footerPeriod')}
        </p>
      </main>
    </div>
  )
}
