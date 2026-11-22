import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { getRandomTip } from './helpContent'

/** First-load placeholder for the 2D map, matching the globe's loading view. */
export default function MapDataLoading({ message }: { message: string }) {
  const { t } = useTranslation('map')
  const tip = useMemo(() => getRandomTip(t), [t])
  return <div role="status" aria-live="polite" className="flex-1 flex items-center justify-center">
    <div className="text-center text-gray-400">
      <div className="relative inline-block w-20 h-20 mb-4">
        <div className="absolute inset-0 rounded-full border border-gray-600 animate-ping opacity-30" />
        <div className="absolute inset-0 rounded-full border border-neon-cyan/40 animate-pulse" />
        <div className="absolute inset-4 rounded-full bg-neon-cyan/10 flex items-center justify-center">
          <div className="w-3 h-3 rounded-full bg-neon-cyan/60 animate-pulse" />
        </div>
      </div>
      <div className="text-sm">{message}</div>
      <div className="mt-3 text-xs text-gray-600 max-w-xs mx-auto leading-relaxed">{tip}</div>
    </div>
  </div>
}
