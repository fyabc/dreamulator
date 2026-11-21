import { useId, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

const models = ['ebm', 'eps', 'epsPlus'] as const
type ClimateModel = typeof models[number]

export function ClimateModelPicker() {
  const { t } = useTranslation('playground')
  const id = useId()
  const trigger = useRef<HTMLButtonElement>(null)
  const [expanded, setExpanded] = useState(false)
  const [hovered, setHovered] = useState<ClimateModel | null>(null)
  const [focused, setFocused] = useState<ClimateModel | null>(null)

  function close(restoreFocus = false) {
    setExpanded(false)
    setHovered(null)
    setFocused(null)
    if (restoreFocus) trigger.current?.focus()
  }

  return <div onBlur={event => {
    if (!event.currentTarget.contains(event.relatedTarget)) close()
  }} onKeyDown={event => {
    if (event.key !== 'Escape' || !expanded) return
    event.preventDefault()
    event.stopPropagation()
    close(true)
  }}>
    <div className="flex items-center justify-between gap-3">
      <span id={`${id}-label`} className="text-xs font-semibold text-gray-200">{t('ebm.model.label')}</span>
      <button ref={trigger} type="button" aria-expanded={expanded} aria-controls={`${id}-choices`}
        aria-labelledby={`${id}-label ${id}-value`}
        onClick={() => expanded ? close() : setExpanded(true)}
        className="atlas-tool-button min-h-9 min-w-24 justify-between text-xs focus-visible:outline focus-visible:outline-neon-cyan">
        <span id={`${id}-value`}>{t('ebm.model.ebm.name')}</span>
        <svg aria-hidden="true" viewBox="0 0 16 16" className={`size-4 motion-safe:transition-transform ${expanded ? 'rotate-180' : ''}`}
          fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="m4 6 4 4 4-4" />
        </svg>
      </button>
    </div>
    <div id={`${id}-choices`} role="group" aria-labelledby={`${id}-label`} hidden={!expanded}
      onPointerLeave={() => setHovered(null)} className="mt-1.5 rounded-md border border-space-border bg-space-bg p-1">
      {models.map(model => <button key={model} type="button" aria-disabled={model !== 'ebm'}
        aria-pressed={model === 'ebm'} aria-describedby={`${id}-${model}-help`}
        onPointerEnter={event => { if (event.pointerType !== 'touch') setHovered(model) }}
        onFocus={() => { setHovered(null); setFocused(model) }} onBlur={() => setFocused(null)}
        onClick={() => model === 'ebm' ? close(true) : setFocused(model)}
        className={`flex min-h-10 w-full items-center justify-between rounded px-2 text-left text-xs hover:bg-space-surface focus-visible:outline focus-visible:outline-neon-cyan ${model === 'ebm' ? 'font-semibold text-neon-cyan' : 'cursor-not-allowed text-gray-400'}`}>
        {t(`ebm.model.${model}.name`)}
        {model === 'ebm' && <svg aria-hidden="true" viewBox="0 0 16 16" className="size-4" fill="none"
          stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="m3.5 8 3 3 6-6" />
        </svg>}
      </button>)}
      {models.map(model => <p key={model} id={`${id}-${model}-help`} role="tooltip" hidden={(hovered ?? focused) !== model}
        className="mx-2 my-1.5 border-t border-space-border pt-2 text-xs leading-relaxed text-gray-300">
        {t(`ebm.model.${model}.help`)}
      </p>)}
    </div>
  </div>
}
