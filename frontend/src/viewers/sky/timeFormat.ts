/** Time readouts for the sky chart's slider.
 *
 * The engine time is "days since the catalog epoch"; the UI presents an
 * epoch-relative day clock (day N + fraction of a solar day) plus a cosmetic
 * HH:MM dial.  This is NOT local midnight time — deriving that needs
 * hour-angle math the engine does not export (an M4 idea, noted in help).
 */

export interface DayReadout {
  day: number
  fraction: number
}

/** Split at_days into whole solar days + fraction (null solar day → raw days). */
export function dayReadout(atDays: number, solarDayDays: number | null): DayReadout {
  if (solarDayDays === null || solarDayDays <= 0) {
    return { day: atDays, fraction: 0.0 }
  }
  return { day: Math.floor(atDays / solarDayDays), fraction: atDays / solarDayDays % 1.0 }
}

/** Cosmetic epoch-relative dial HH:MM from the solar-day fraction. */
export function dayClock(atDays: number, solarDayDays: number | null): string | null {
  if (solarDayDays === null || solarDayDays <= 0) return null
  const fraction = ((atDays / solarDayDays) % 1.0 + 1.0) % 1.0
  const totalMinutes = Math.round(fraction * 24 * 60) % (24 * 60)
  const hh = Math.floor(totalMinutes / 60)
  const mm = totalMinutes % 60
  return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`
}

/** Slider range: the observer's "year" — parent's orbital period when the
 *  observer is a satellite, else its own; a bounded fallback keeps the
 *  control usable even on sparse catalogs. */
export const SLIDER_FALLBACK_DAYS = 100

export function sliderYearDays(
  catalog: { bodies?: unknown[] | null },
  observerId: string,
): number {
  interface Periodic {
    id?: string | null
    parent_id?: string | null
    orbit?: { period_days?: number | null } | null
  }
  const bodies = (catalog.bodies ?? []) as Periodic[]
  const observer = bodies.find((b) => b.id === observerId)
  if (observer?.orbit?.period_days && observer.orbit.period_days > 0) {
    const parent = bodies.find((b) => b.id === observer.parent_id)
    const parentPeriod = parent?.orbit?.period_days
    if (observer.parent_id && parentPeriod && parentPeriod > 0) return parentPeriod
    return observer.orbit.period_days
  }
  return SLIDER_FALLBACK_DAYS
}

/** Slider step: 1/24 of a solar day (stops on even hour fractions). */
export function sliderStep(solarDayDays: number | null): number {
  if (solarDayDays === null || solarDayDays <= 0) return 0.01
  return solarDayDays / 24
}
