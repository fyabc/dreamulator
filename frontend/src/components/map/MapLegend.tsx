import { useTranslation } from 'react-i18next'

/**
 * Base-map water/land legend for the map viewer.
 *
 * The terrain and landsea base maps encode the water split in colour: deep
 * ocean blue, land green/brown, inland lakes light cyan (frozen lakes pale
 * grey-blue). None of that is explained anywhere else in the UI — the layer
 * panel shows only names and opacity — so this compact legend floats over
 * the map's bottom-left corner whenever a base map is active.
 */

const LAKE = '#67e6dc'
const FROZEN_LAKE = '#c8e1eb'
const OCEAN = '#1a5276'
const LAND = '#4caf50'

export default function MapLegend({ visible }: { visible: boolean }) {
  const { t } = useTranslation('map')
  if (!visible) return null

  const items: Array<{ color: string; key: string }> = [
    { color: OCEAN, key: 'legend.ocean' },
    { color: LAND, key: 'legend.land' },
    { color: LAKE, key: 'legend.lake' },
    { color: FROZEN_LAKE, key: 'legend.frozenLake' },
  ]

  return (
    <div
      className="absolute bottom-3 left-3 z-30 rounded-md border border-space-border bg-space-panel/80 px-3 py-2 backdrop-blur-sm pointer-events-none"
      data-testid="map-legend"
    >
      <div className="flex flex-col gap-1.5">
        {items.map((it) => (
          <div key={it.key} className="flex items-center gap-2">
            <span
              className="w-3 h-3 rounded-sm shrink-0 border border-black/30"
              style={{ backgroundColor: it.color }}
            />
            <span className="text-[11px] text-gray-300 whitespace-nowrap">
              {t(it.key)}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
