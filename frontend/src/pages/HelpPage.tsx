import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useLocation } from 'react-router-dom'
import { HELP_SECTIONS, type HelpSection } from '../components/map/helpContent'
import { isStaticMode } from '../api/mode'
import { temperatureSampleOrigins, temperatureTrialMapPath } from '../playground/temperatureDraft'

const startId = 'start'

function renderInline(text: string) {
  return text.split(/(`[^`\n]+`|\*\*[^*\n]+\*\*|\n)/g).map((part, index) => {
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
      return <code key={index} className="rounded bg-space-surface px-1 py-0.5 text-sm text-neon-cyan">{part.slice(1, -1)}</code>
    }
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return <strong key={index} className="text-gray-200">{part.slice(2, -2)}</strong>
    }
    return part === '\n' ? <br key={index} /> : part
  })
}

function renderContent(text: string) {
  return text.split('\n\n').map((block, i) => {
    const trimmed = block.trim()
    if (!trimmed) return null

    if (trimmed.startsWith('```')) {
      const lines = trimmed.split('\n')
      const code = lines.slice(1, -1).join('\n')
      return (
        <pre key={i} className="bg-black/30 rounded-lg p-3 my-2 overflow-x-auto">
          <code className="text-xs text-gray-300 font-mono whitespace-pre-wrap">{code}</code>
        </pre>
      )
    }

    if (trimmed.startsWith('- ')) {
      const items = trimmed.split('\n').filter((l) => l.startsWith('- '))
      return (
        <ul key={i} className="my-2 list-disc space-y-1 pl-5 text-sm leading-relaxed text-gray-300">
          {items.map((item, j) => (
            <li key={j}>{renderInline(item.slice(2))}</li>
          ))}
        </ul>
      )
    }

    return (
      <p key={i} className="mb-2 text-sm leading-relaxed text-gray-300">{renderInline(trimmed)}</p>
    )
  })
}

function SectionContent({ section }: { section: HelpSection }) {
  const { t } = useTranslation('help')
  const entries = section.render(t)

  return (
    <section id={section.id} className="scroll-mt-16 space-y-5 border-t border-space-border pt-6 lg:scroll-mt-6"
      aria-labelledby={`help-heading-${section.id}`}>
      <h2 id={`help-heading-${section.id}`} tabIndex={-1} className="text-xl font-semibold text-gray-100">{t(section.title)}</h2>
      {entries.map((entry, i) => (
        <div key={i} className="break-words">
          <h3 className="mb-2 text-base font-semibold text-gray-100">{entry.title}</h3>
          {renderContent(entry.content)}
        </div>
      ))}
    </section>
  )
}

function GettingStarted() {
  const { t } = useTranslation('help')
  const mode = isStaticMode() ? 'static' : 'local'
  const entry = mode === 'static' ? '/worlds' : '/import'
  const steps = [
    { key: 'first', to: entry },
    { key: 'second', to: mode === 'static' ? '#region-selection' : '/worlds' },
    { key: 'third', to: '#packs' },
  ] as const

  return (
    <header id={startId} className="scroll-mt-16 lg:scroll-mt-6">
      <h1 id={`help-heading-${startId}`} tabIndex={-1} className="text-3xl font-semibold tracking-tight text-gray-100">{t('start.title')}</h1>
      <p className="mt-3 leading-relaxed text-gray-300">{t(`start.${mode}.intro`)}</p>
      <ol className="mt-5 list-decimal space-y-4 pl-5 marker:font-semibold marker:text-neon-cyan">
        {steps.map(({ key, to }) => (
          <li key={key} className="pl-1">
            <Link to={to} className="inline-flex min-h-8 items-center rounded font-semibold text-neon-cyan underline-offset-4 hover:underline">
              {t(`start.${mode}.${key}.action`)}
            </Link>
            <p className="text-sm leading-relaxed text-gray-300">{t(`start.${mode}.${key}.description`)}</p>
          </li>
        ))}
      </ol>
      <p className="mt-5 text-sm leading-relaxed text-gray-300">{t(`start.${mode}.backup`)}</p>
      <div className="mt-4 border-t border-space-border pt-3">
        <p className="text-sm text-gray-300">{t('start.temperatureSamples')}</p>
        <ul className="flex flex-wrap gap-x-5">
          {Object.entries(temperatureSampleOrigins).map(([sample, origin]) => (
            <li key={sample}>
              <Link to={temperatureTrialMapPath(mode === 'local' && sample === 'earth' ? { ...origin, branch: 'climate-dev' } : origin)} className="inline-flex min-h-11 items-center rounded text-sm font-semibold text-neon-cyan underline-offset-4 hover:underline focus-visible:outline focus-visible:outline-neon-cyan">
                {t(`start.temperatureSample.${sample}`)}
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </header>
  )
}

export default function HelpPage() {
  const { t } = useTranslation('help')
  const { hash, key } = useLocation()
  const page = useRef<HTMLDivElement>(null)
  const mobileToc = useRef<HTMLDetailsElement>(null)
  const entries = [{ id: startId, title: 'start.title' }, ...HELP_SECTIONS]
  const target = hash.slice(1)
  const activeSection = entries.some(({ id }) => id === target) ? target : startId

  useEffect(() => {
    if (mobileToc.current) mobileToc.current.open = false
    if (!target || target !== activeSection) {
      page.current?.scrollTo({ top: 0 })
      return
    }
    document.getElementById(`help-heading-${target}`)?.focus({ preventScroll: true })
    document.getElementById(target)?.scrollIntoView({ block: 'start' })
  }, [activeSection, key, target])

  const contents = <nav aria-label={t('start.contents')}>
    <ul className="space-y-0.5">
      {entries.map(({ id, title }) => (
        <li key={id}>
          <Link to={{ hash: `#${id}` }} aria-current={id === activeSection ? 'location' : undefined}
            className={`block rounded px-3 py-2 text-sm ${id === activeSection ? 'bg-space-surface font-semibold text-neon-cyan' : 'text-gray-300 hover:bg-space-surface'}`}>
            {t(title)}
          </Link>
        </li>
      ))}
    </ul>
  </nav>

  return (
    <div ref={page} className="h-[calc(100dvh-3.5rem)] overflow-y-auto md:h-dvh">
      <div className="mx-auto flex max-w-6xl flex-col gap-4 px-4 py-4 sm:px-6 lg:grid lg:grid-cols-[12rem_minmax(0,1fr)] lg:gap-10 lg:px-8 lg:py-6">
        <div className="sticky top-0 z-10 bg-space-bg py-1 lg:top-6 lg:max-h-[calc(100dvh-3rem)] lg:self-start lg:overflow-y-auto lg:p-1">
          <details ref={mobileToc} className="rounded border border-space-border lg:hidden">
            <summary className="cursor-pointer px-3 py-3 text-sm font-medium text-gray-200">{t('start.contents')}</summary>
            <div className="max-h-[50dvh] overflow-y-auto px-1 pb-1">{contents}</div>
          </details>
          <div className="hidden lg:block">
            <p className="mb-2 px-3 text-sm font-semibold text-gray-200">{t('start.contents')}</p>
            {contents}
          </div>
        </div>
        <article className="w-full min-w-0 max-w-[72ch] space-y-10 pb-12">
          <GettingStarted />
          {HELP_SECTIONS.map((section) => <SectionContent key={section.id} section={section} />)}
        </article>
      </div>
    </div>
  )
}
