import { Navigate, useSearchParams } from 'react-router-dom'
import { legacyTemperatureTrialDestination, temperatureSamplesHelpPath } from '../playground/temperatureDraft'

export default function PlaygroundPage() {
  const [search] = useSearchParams()
  return <Navigate to={legacyTemperatureTrialDestination(search) ?? temperatureSamplesHelpPath} replace />
}
