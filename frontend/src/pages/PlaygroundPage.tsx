import { Navigate, useSearchParams } from 'react-router-dom'
import TemperatureLab from '../playground/TemperatureLab'
import { legacyTemperatureDraftDestination } from '../playground/temperatureDraft'

export default function PlaygroundPage() {
  const [search] = useSearchParams()
  const map = legacyTemperatureDraftDestination(search)
  if (map) return <Navigate to={map} replace />
  return <TemperatureLab key={search.toString()} search={search} />
}
