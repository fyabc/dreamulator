import { useSearchParams } from 'react-router-dom'
import TemperatureLab from '../playground/TemperatureLab'

export default function PlaygroundPage() {
  const [search] = useSearchParams()
  return <TemperatureLab key={search.toString()} search={search} />
}
