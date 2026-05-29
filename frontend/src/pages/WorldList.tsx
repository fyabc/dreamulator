import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useState } from 'react'
import { api } from '../api/client'

export default function WorldList() {
  const queryClient = useQueryClient()
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [newWorldName, setNewWorldName] = useState('')
  const [newWorldTemplate, setNewWorldTemplate] = useState('minimal')

  const { data: worlds, isLoading, error } = useQuery({
    queryKey: ['worlds'],
    queryFn: api.listWorlds,
  })

  const createMutation = useMutation({
    mutationFn: ({ name, template }: { name: string; template: string }) =>
      api.createWorld(name, template),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['worlds'] })
      setShowCreateDialog(false)
      setNewWorldName('')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (name: string) => api.deleteWorld(name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['worlds'] })
    },
  })

  const handleCreate = () => {
    if (newWorldName.trim()) {
      createMutation.mutate({ name: newWorldName, template: newWorldTemplate })
    }
  }

  if (isLoading) {
    return <div className="text-center py-12">Loading worlds...</div>
  }

  if (error) {
    return (
      <div className="text-center py-12 text-red-400">
        Error loading worlds: {error.message}
      </div>
    )
  }

  return (
    <div>
      <div className="flex justify-between items-center mb-8">
        <h1 className="text-3xl font-bold">Worlds</h1>
        <button
          onClick={() => setShowCreateDialog(true)}
          className="bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg font-medium transition-colors"
        >
          + New World
        </button>
      </div>

      {worlds && worlds.length > 0 ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {worlds.map((worldName) => (
            <div
              key={worldName}
              className="bg-gray-800 border border-gray-700 rounded-lg p-6 hover:border-blue-500 transition-colors"
            >
              <Link to={`/worlds/${worldName}`} className="block">
                <h3 className="text-xl font-semibold mb-2 text-blue-400">
                  {worldName}
                </h3>
              </Link>
              <div className="flex gap-2 mt-4">
                <Link
                  to={`/worlds/${worldName}`}
                  className="text-sm bg-gray-700 hover:bg-gray-600 px-3 py-1 rounded transition-colors"
                >
                  Open
                </Link>
                <button
                  onClick={() => {
                    if (confirm(`Delete world "${worldName}"?`)) {
                      deleteMutation.mutate(worldName)
                    }
                  }}
                  className="text-sm bg-red-900 hover:bg-red-800 px-3 py-1 rounded transition-colors"
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-center py-12 text-gray-400">
          <p className="text-lg mb-4">No worlds yet</p>
          <button
            onClick={() => setShowCreateDialog(true)}
            className="bg-blue-600 hover:bg-blue-700 px-6 py-3 rounded-lg font-medium transition-colors"
          >
            Create Your First World
          </button>
        </div>
      )}

      {showCreateDialog && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-lg p-6 w-full max-w-md border border-gray-700">
            <h2 className="text-2xl font-bold mb-4">Create New World</h2>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-2">
                  World Name
                </label>
                <input
                  type="text"
                  value={newWorldName}
                  onChange={(e) => setNewWorldName(e.target.value)}
                  placeholder="my_world"
                  className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2 focus:outline-none focus:border-blue-500"
                  autoFocus
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-2">
                  Template
                </label>
                <select
                  value={newWorldTemplate}
                  onChange={(e) => setNewWorldTemplate(e.target.value)}
                  className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2 focus:outline-none focus:border-blue-500"
                >
                  <option value="minimal">Minimal</option>
                  <option value="earthlike">Earth-like</option>
                </select>
              </div>

              {createMutation.error && (
                <div className="text-red-400 text-sm">
                  Error: {createMutation.error.message}
                </div>
              )}

              <div className="flex gap-3 pt-4">
                <button
                  onClick={handleCreate}
                  disabled={createMutation.isPending}
                  className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 px-4 py-2 rounded-lg font-medium transition-colors"
                >
                  {createMutation.isPending ? 'Creating...' : 'Create'}
                </button>
                <button
                  onClick={() => setShowCreateDialog(false)}
                  className="flex-1 bg-gray-700 hover:bg-gray-600 px-4 py-2 rounded-lg font-medium transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
