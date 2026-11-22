import { useTranslation } from 'react-i18next'

/** Annual/monthly switch, shown in the map toolbar next to the layer switch. */
export default function TimeModeToggle({ monthlyMode, onChange, disabled = false }: {
  monthlyMode: boolean
  onChange: (monthly: boolean) => void
  disabled?: boolean
}) {
  const { t } = useTranslation('map')
  return <div role="group" aria-label={t('time.title')}
    className="inline-flex shrink-0 items-center gap-0.5 whitespace-nowrap rounded border border-space-border bg-space-bg p-0.5">
    <button type="button" onClick={() => onChange(false)} aria-pressed={!monthlyMode}
      title={t('time.annualHint')}
      className={`min-h-9 rounded px-2.5 text-sm transition-colors ${!monthlyMode
        ? 'bg-space-surface font-semibold text-gray-100 ring-1 ring-inset ring-neon-cyan/30' : 'text-gray-300 hover:bg-space-surface'}`}>
      {t('time.annual')}
    </button>
    <button type="button" onClick={() => onChange(true)} aria-pressed={monthlyMode} disabled={disabled}
      data-tutorial-anchor="monthly" title={t('time.monthlyHint')}
      className={`min-h-9 rounded px-2.5 text-sm transition-colors disabled:opacity-40 ${monthlyMode
        ? 'bg-space-surface font-semibold text-gray-100 ring-1 ring-inset ring-neon-cyan/30' : 'text-gray-300 hover:bg-space-surface'}`}>
      {t('time.monthly')}
    </button>
  </div>
}
