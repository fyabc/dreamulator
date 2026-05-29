import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import { api } from '../api/client'
import { useState } from 'react'

export default function WorldDetail() {
  const { worldName } = useParams<{ worldName: string }>()
  const [activeTab, setActiveTab] = useState<'overview' | 'stellar' | 'planets'>('overview')

  const { data: world, isLoading, error } = useQuery({
    queryKey: ['world', worldName],
    queryFn: () => api.getWorld(worldName!),
    enabled: !!worldName,
  })

  const { data: stellarSystem } = useQuery({
    queryKey: ['stellar', worldName],
    queryFn: () => api.getStellarSystem(worldName!),
    enabled: !!worldName && activeTab === 'stellar',
  })

  const { data: planets } = useQuery({
    queryKey: ['planets', worldName],
    queryFn: () => api.getPlanets(worldName!),
    enabled: !!worldName && activeTab === 'planets',
  })

  const buildMutation = useMutation({
    mutationFn: () => api.buildWorld(worldName!),
  })

  const validateMutation = useMutation({
    mutationFn: () => api.validateWorld(worldName!),
  })

  if (!worldName) {
    return <div className="text-center py-12">No world selected</div>
  }

  if (isLoading) {
    return <div className="text-center py-12">Loading world...</div>
  }

  if (error) {
    return (
      <div className="text-center py-12 text-red-400">
        Error loading world: {error.message}
      </div>
    )
  }

  return (
    <div>
      <div className="flex items-center gap-4 mb-6">
        <Link to="/worlds" className="text-gray-400 hover:text-gray-200">
          ← Back
        </Link>
        <h1 className="text-3xl font-bold">{worldName}</h1>
      </div>

      <div className="flex gap-3 mb-6">
        <button
          onClick={() => validateMutation.mutate()}
          disabled={validateMutation.isPending}
          className="bg-gray-700 hover:bg-gray-600 px-4 py-2 rounded-lg font-medium transition-colors"
        >
          {validateMutation.isPending ? 'Validating...' : 'Validate'}
        </button>
        <button
          onClick={() => buildMutation.mutate()}
          disabled={buildMutation.isPending}
          className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 px-4 py-2 rounded-lg font-medium transition-colors"
        >
          {buildMutation.isPending ? 'Building...' : 'Build'}
        </button>
      </div>

      {validateMutation.data && (
        <div className={`mb-6 p-4 rounded-lg ${validateMutation.data.valid ? 'bg-green-900' : 'bg-red-900'}`}>
          <p className="font-semibold mb-2">
            {validateMutation.data.valid ? '✓ Valid' : '✗ Invalid'}
          </p>
          {validateMutation.data.errors.length > 0 && (
            <ul className="list-disc list-inside text-sm">
              {validateMutation.data.errors.map((err, i) => (
                <li key={i}>{err}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="flex gap-2 mb-6 border-b border-gray-700">
        {(['overview', 'stellar', 'planets'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 font-medium transition-colors border-b-2 ${
              activeTab === tab
                ? 'border-blue-500 text-blue-400'
                : 'border-transparent text-gray-400 hover:text-gray-200'
            }`}
          >
            {tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      {activeTab === 'overview' && world && (
        <div className="space-y-6">
          <section className="bg-gray-800 rounded-lg p-6 border border-gray-700">
            <h2 className="text-xl font-semibold mb-4">Metadata</h2>
            <dl className="grid grid-cols-2 gap-4">
              <div>
                <dt className="text-gray-400 text-sm">Created</dt>
                <dd className="font-medium">{world.metadata?.created || 'N/A'}</dd>
              </div>
              <div>
                <dt className="text-gray-400 text-sm">Version</dt>
                <dd className="font-medium">{world.metadata?.version || 'N/A'}</dd>
              </div>
              <div>
                <dt className="text-gray-400 text-sm">Seed</dt>
                <dd className="font-medium">{world.seed?.seed || 'N/A'}</dd>
              </div>
              <div>
                <dt className="text-gray-400 text-sm">Dreamulator Version</dt>
                <dd className="font-medium">{world.metadata?.dreamulator_version || 'N/A'}</dd>
              </div>
            </dl>
          </section>

          {world.stellar_system && (
            <section className="bg-gray-800 rounded-lg p-6 border border-gray-700">
              <h2 className="text-xl font-semibold mb-4">Stellar System</h2>
              <p className="mb-2">
                <span className="text-gray-400">Name:</span>{' '}
                {world.stellar_system.name}
              </p>
              <p className="mb-2">
                <span className="text-gray-400">Stars:</span>{' '}
                {world.stellar_system.stars?.length || 0}
              </p>
              <p>
                <span className="text-gray-400">Orbits:</span>{' '}
                {world.stellar_system.orbits?.length || 0}
              </p>
            </section>
          )}
        </div>
      )}

      {activeTab === 'stellar' && (
        <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
          <h2 className="text-xl font-semibold mb-4">Stellar System</h2>
          {stellarSystem ? (
            <div>
              <p className="mb-4">
                <span className="text-gray-400">System Name:</span>{' '}
                {stellarSystem.name}
              </p>
              <h3 className="text-lg font-semibold mb-3">Stars</h3>
              <div className="space-y-3">
                {stellarSystem.stars?.map((star: any) => (
                  <div key={star.id} className="bg-gray-700 rounded-lg p-4">
                    <p className="font-semibold text-blue-400 mb-2">
                      {star.name} ({star.id})
                    </p>
                    <div className="grid grid-cols-2 gap-2 text-sm">
                      <p>
                        <span className="text-gray-400">Type:</span>{' '}
                        {star.spectral_class}
                        {star.luminosity_class}
                      </p>
                      <p>
                        <span className="text-gray-400">Mass:</span>{' '}
                        {star.mass} M☉
                      </p>
                      {star.temperature && (
                        <p>
                          <span className="text-gray-400">Temperature:</span>{' '}
                          {star.temperature} K
                        </p>
                      )}
                      {star.luminosity && (
                        <p>
                          <span className="text-gray-400">Luminosity:</span>{' '}
                          {star.luminosity} L☉
                        </p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-gray-400">Loading stellar system...</p>
          )}
        </div>
      )}

      {activeTab === 'planets' && (
        <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
          <h2 className="text-xl font-semibold mb-4">Planets</h2>
          {planets ? (
            <div className="space-y-3">
              {planets.length > 0 ? (
                planets.map((planet: any) => (
                  <div key={planet.id} className="bg-gray-700 rounded-lg p-4">
                    <p className="font-semibold text-blue-400 mb-2">
                      {planet.name} ({planet.id})
                    </p>
                    <div className="grid grid-cols-2 gap-2 text-sm">
                      <p>
                        <span className="text-gray-400">Type:</span>{' '}
                        {planet.planet_type}
                      </p>
                      <p>
                        <span className="text-gray-400">Orbits:</span>{' '}
                        {planet.orbits}
                      </p>
                      <p>
                        <span className="text-gray-400">Mass:</span>{' '}
                        {planet.mass} M⊕
                      </p>
                      <p>
                        <span className="text-gray-400">Radius:</span>{' '}
                        {planet.radius} R⊕
                      </p>
                    </div>
                  </div>
                ))
              ) : (
                <p className="text-gray-400">No planets defined</p>
              )}
            </div>
          ) : (
            <p className="text-gray-400">Loading planets...</p>
          )}
        </div>
      )}
    </div>
  )
}
