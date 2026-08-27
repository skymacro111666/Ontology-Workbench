import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Envelope, NodesEdges } from '../api/types'
import { useBrowseStore } from '../stores/browseStore'
import { useUiStore } from '../stores/uiStore'
import { ThemeProvider } from '../theme/ThemeProvider'
import EntityDialogs from './EntityDialogs'

/* The A2 dialog family: mode-driven form, POST/PUT/DELETE bodies carrying
   the meta query's baseFileHash, invalidate on success, inline duplicate
   error. */

const OID = 'oid-1'
const DOG = 'http://example.org/Dog'
const TOY = 'http://example.org/Toy'

const META = {
  id: OID,
  title: 'Mini',
  filename: 'mini.ttl',
  format: 'turtle',
  classCount: 5,
  propertyCount: 2,
  axiomCount: 9,
  instanceCount: 0,
  fileSizeBytes: 100,
  fileHash: 'hash-1',
  prefixes: { ex: 'http://example.org/' },
  createdAt: '2026-08-26T00:00:00',
}

const OVERVIEW: NodesEdges = {
  nodes: [
    { id: DOG, curie: 'ex:Dog', label: {}, kind: 'class' },
    { id: TOY, curie: 'ex:Toy', label: {}, kind: 'class' },
  ],
  edges: [],
  truncated: false,
  totalCount: 2,
}

const ENTITY = {
  eid: DOG,
  curie: 'ex:Dog',
  type: 'Class',
  label: { zh: '狗' },
  comment: 'Woof.',
  deprecated: false,
  parents: [{ eid: TOY, curie: 'ex:Toy', label: {} }],
  children: [],
  properties: [],
  referencedBy: [],
  axioms: [],
  stats: { directChildren: 0, totalDescendants: 0 },
}

function env(data: unknown, code = 'OK') {
  return new Response(
    JSON.stringify({ code, message: 'ok', data, hint: null, request_id: 'r' } satisfies Envelope<unknown>),
    { headers: { 'Content-Type': 'application/json' } },
  )
}

interface CallLog {
  post: { url: string; body: Record<string, unknown> }[]
  put: { url: string; body: Record<string, unknown> }[]
  del: string[]
}

let calls: CallLog

function stubFetch(opts: { dupOnPost?: boolean } = {}) {
  calls = { post: [], put: [], del: [] }
  return vi.fn(async (url: string | URL, init?: RequestInit) => {
    const u = String(url)
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : {}
    if (method === 'POST') {
      calls.post.push({ url: u, body })
      if (opts.dupOnPost) return env(null, 'DUPLICATE_ENTITY')
      return env({ meta: META, entity: { eid: DOG, curie: 'ex:Cat', type: 'Class' } })
    }
    if (method === 'PUT') {
      calls.put.push({ url: u, body })
      return env({ meta: META, entity: { eid: DOG, curie: 'ex:Dog', type: 'Class' } })
    }
    if (method === 'DELETE') {
      calls.del.push(u)
      return env({ removed: 3, meta: META })
    }
    if (u.endsWith('/meta')) return env(META)
    if (u.endsWith('/overview')) return env(OVERVIEW)
    if (u.includes('/entities/')) return env(ENTITY)
    return env({})
  })
}

function draw(fetchMock: ReturnType<typeof stubFetch>) {
  vi.stubGlobal('fetch', fetchMock)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <EntityDialogs oid={OID} />
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useUiStore.setState({ entityDialog: null })
  useBrowseStore.setState({ selectedEid: null, revealEid: null })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('EntityDialogs', () => {
  it('creates a class: form → POST body carries name/prefix/parents/baseFileHash', async () => {
    const fetchMock = stubFetch()
    draw(fetchMock)
    useUiStore.getState().setEntityDialog({ mode: 'class' })
    const name = await screen.findByLabelText(/名称/)
    await userEvent.type(name, 'Cat')
    // Parent picker: choose Dog from the class list.
    await userEvent.click(await screen.findByText('Dog'))
    await userEvent.click(screen.getByRole('button', { name: /创建|保存/ }))

    await waitFor(() => expect(calls.post).toHaveLength(1))
    const { url, body } = calls.post[0]
    expect(url).toBe(`/api/ontologies/${OID}/classes`)
    expect(body).toMatchObject({
      name: 'Cat',
      prefix: 'ex',
      label: { value: 'Cat', lang: null },
      parents: [DOG],
      baseFileHash: 'hash-1',
    })
    // Success closes the dialog.
    await waitFor(() => expect(useUiStore.getState().entityDialog).toBeNull())
  })

  it('pre-fills the subclass parent from the menu context', async () => {
    const fetchMock = stubFetch()
    draw(fetchMock)
    useUiStore.getState().setEntityDialog({ mode: 'subclass', parent: DOG })
    await screen.findByLabelText(/名称/)
    await userEvent.type(screen.getByLabelText(/名称/), 'Puppy')
    await userEvent.click(screen.getByRole('button', { name: /创建|保存/ }))
    await waitFor(() => expect(calls.post).toHaveLength(1))
    expect(calls.post[0].body.parents).toEqual([DOG])
  })

  it('shows an inline duplicate-name error', async () => {
    const fetchMock = stubFetch({ dupOnPost: true })
    draw(fetchMock)
    useUiStore.getState().setEntityDialog({ mode: 'class' })
    await userEvent.type(await screen.findByLabelText(/名称/), 'Dog')
    await userEvent.click(screen.getByRole('button', { name: /创建|保存/ }))
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(useUiStore.getState().entityDialog).not.toBeNull()
  })

  it('edits an entity: comment PUT, label untouched (no label UI)', async () => {
    const fetchMock = stubFetch()
    draw(fetchMock)
    useUiStore.getState().setEntityDialog({ mode: 'editClass', eid: DOG })
    const comment = await screen.findByLabelText(/描述/)
    await userEvent.clear(comment)
    await userEvent.type(comment, 'Good dog.')
    await userEvent.click(screen.getByRole('button', { name: /创建|保存/ }))
    await waitFor(() => expect(calls.put).toHaveLength(1))
    expect(calls.put[0].url).toBe(
      `/api/ontologies/${OID}/entities/${encodeURIComponent(DOG)}`,
    )
    expect(calls.put[0].body).toMatchObject({ baseFileHash: 'hash-1', comment: 'Good dog.' })
    // No label row: the request must not carry a label key at all.
    expect(calls.put[0].body).not.toHaveProperty('label')
    expect(screen.queryByLabelText(/标签/)).toBeNull()
  })

  it('deletes with prune and the lock in the query string', async () => {
    const fetchMock = stubFetch()
    draw(fetchMock)
    useUiStore.getState().setEntityDialog({ mode: 'delete', eid: DOG })
    await screen.findByText('删除实体')
    await userEvent.click(screen.getByRole('button', { name: '删除' }))
    await waitFor(() => expect(calls.del).toHaveLength(1))
    expect(calls.del[0]).toContain(`/api/ontologies/${OID}/entities/${encodeURIComponent(DOG)}`)
    expect(calls.del[0]).toContain('baseFileHash=hash-1')
    expect(calls.del[0]).toContain('prune=true')
    await waitFor(() => expect(useUiStore.getState().entityDialog).toBeNull())
  })
})
