import { assertProjectCapacity, projectBytes, type LocalProject } from './elevationProject'

const storeName = 'projects'
export const projectsKey = ['browser-projects'] as const
export const projectKey = (id: string) => [...projectsKey, id]
export const worldDataPath = (id: string, branch?: string | null) =>
  `/worlds/${encodeURIComponent(id)}?tab=data${branch ? `&branch=${encodeURIComponent(branch)}` : ''}`

export function projectRegionPath(id: string, layerId: string, branch?: string | null) {
  const search = new URLSearchParams({ project: id, layer: layerId })
  if (branch) search.set('branch', branch)
  return `/packs?${search}`
}

function openProjects() {
  return new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open('dreamulator-projects', 1)
    request.onupgradeneeded = () => request.result.createObjectStore(storeName, { keyPath: 'id' })
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

async function transact<Result>(mode: IDBTransactionMode, action: (
  store: IDBObjectStore, setResult: (result: Result) => void, fail: (error: unknown) => void,
) => void) {
  const database = await openProjects()
  try {
    return await new Promise<Result>((resolve, reject) => {
      const transaction = database.transaction(storeName, mode)
      let result: Result
      let cause: unknown
      const fail = (error: unknown) => { cause = error; transaction.abort() }
      transaction.oncomplete = () => resolve(result)
      transaction.onabort = () => reject(cause ?? transaction.error)
      try { action(transaction.objectStore(storeName), (value) => { result = value }, fail) }
      catch (error) { fail(error) }
    })
  } finally { database.close() }
}

export function getProject(id: string) {
  return transact<LocalProject | null>('readonly', (store, done) => {
    const request = store.get(id)
    request.onsuccess = () => done(request.result ?? null)
  })
}

export function listProjects() {
  return transact<LocalProject[]>('readonly', (store, done) => {
    const request = store.getAll()
    request.onsuccess = () => done(request.result)
  }).then((projects) => projects.map((project) => ({ id: project.id, name: project.name, updatedAt: project.updatedAt, published: project.published,
    layers: project.layers.length, bytes: projectBytes(project) })).sort((left, right) => right.updatedAt - left.updatedAt))
}

export async function addProject(project: LocalProject) {
  assertProjectCapacity(project)
  await transact<void>('readwrite', (store) => { store.add(project) })
  return project.id
}

export function createProject(name: string) {
  return addProject({ id: crypto.randomUUID(), name: name.trim().slice(0, 200), updatedAt: Date.now(), layers: [] })
}

export function updateProject(id: string, update: (project: LocalProject) => LocalProject, initial?: LocalProject) {
  return transact<void>('readwrite', (store, _done, fail) => {
    const request = store.get(id)
    request.onsuccess = () => {
      try {
        const current: LocalProject | undefined = request.result ?? initial
        if (!current) throw new Error('World is missing')
        if (initial && current.published !== initial.published) throw new Error('World identity conflict')
        const next = { ...update(current), updatedAt: Date.now() }
        assertProjectCapacity(next)
        store.put(next)
      } catch (error) { fail(error) }
    }
  })
}

export function publishedWorld(id: string): LocalProject {
  return { id, name: id, published: true, updatedAt: Date.now(), layers: [] }
}

export async function restoreWorld(world: LocalProject) {
  if (!world.published) {
    try { return await addProject(world) }
    catch (error) {
      if (!(error instanceof DOMException) || error.name !== 'ConstraintError') throw error
      return addProject({ ...world, id: crypto.randomUUID(), layers: copyLayers(world) })
    }
  }
  await updateProject(world.id, (current) => {
    const existing = new Set(current.layers.map((layer) => layer.id))
    const imported = world.layers.some((layer) => existing.has(layer.id)) ? copyLayers(world) : world.layers
    return { ...current, layers: [...current.layers, ...imported] }
  }, publishedWorld(world.id))
  return world.id
}

function copyLayers(world: LocalProject): LocalProject['layers'] {
  const ids = new Map(world.layers.map((layer) => [layer.id, crypto.randomUUID()]))
  return world.layers.map((layer) => ({ ...layer, id: ids.get(layer.id)!,
    ...(layer.kind === 'elevation-result' && { sourceId: ids.get(layer.sourceId)! }) }))
}

export function deleteProject(id: string) {
  return transact<void>('readwrite', (store) => { store.delete(id) })
}

export function removeProjectLayer(project: LocalProject, id: string): LocalProject {
  if (project.layers.some((layer) => layer.kind === 'elevation-result' && layer.sourceId === id)) throw new Error('Source is still in use')
  return { ...project, layers: project.layers.filter((layer) => layer.id !== id) }
}
