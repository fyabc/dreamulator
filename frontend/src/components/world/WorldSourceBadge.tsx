import { useTranslation } from 'react-i18next'

const styles = {
  browser: 'border-teal-400/30 bg-teal-400/10 text-teal-200',
  published: 'border-sky-400/30 bg-sky-400/10 text-sky-200',
  offline: 'border-space-border bg-space-surface text-gray-300',
}

const labels = { browser: 'localBadge', published: 'publishedBadge', offline: 'browserData' } as const

export default function WorldSourceBadge({ source }: { source: keyof typeof styles }) {
  const { t } = useTranslation('worlds')
  return <span className={`inline-flex rounded border px-2 py-0.5 text-xs font-medium ${styles[source]}`}>
    {t(`worldData.${labels[source]}`)}
  </span>
}
