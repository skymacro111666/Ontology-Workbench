import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Envelope, NodesEdges } from '../api/types'
import { useBrowseStore } from '../stores/browseStore'
import { useUiStore } from '../stores/uiStore'
import { ThemeProvider } from '../theme/ThemeProvider'
import InstanceDialogs from './InstanceDialogs'

/* The B2 instance dialog family: minimal create (POST body carries
   name/prefix/classes/baseFileHash, then reveal + just-created flag) and
   delete confirm (DELETE with the lock, then selection cleared). */

const OID = 'oid-1'
const SF = 'http://example.org/library#ScienceFiction'
const TB2 = 'http://example.org/library#BallLightning'

const META = {
  id: OID,
  title: 'Mini',
  filename: 'mini.ttl',
  format: 'turtle',
  classCount: 1,
  propertyCount: 0,
  axiomCount: 3,
  instanceCount: 0,
  fileSizeBytes: 100,
  fileHash: 'hash-3',
  prefixes: { lib: 'http://example.org/library#' },
  createdAt: '2026-08-26T00:00:00',
}

const OVERVIEW: NodesEdges = {
  nodes: [{ id: SF, curie: 'lib:ScienceFiction', label: {}, kind: 'class' }],
  edges: [],
  truncated: false,
  totalCount: 1,
}

function env(data: unknown, code = 'OK') {
  return new Response(
    JSON.stringify({ code, message: 'ok', data, hint: null, request_id: 'r' } satisfies Envelope<unknown>),
    { headers: { 'Content-Type': 'application/json' } },
  )
}

interface CallLog {
  post: { url: string; body: Record<string, unknown> }[]
  del: string[]
}

let calls: CallLog

function stubFetch(opts: { dupOnPost?: boolean } = {}) {
  calls = { post: [], del: [] }
  return vi.fn(async (url: string | URL, init?: RequestInit) => {
    const u = String(url)
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : {}
    if (method === 'POST') {
      calls.post.push({ url: u, body })
      if (opts.dupOnPost) return env(null, 'DUPLICATE_ENTITY')
      return env({ meta: META, entity: { eid: TB2, curie: 'lib:BallLightning', type: 'Instance' } })
    }
    if (method === 'DELETE') {
      calls.del.push(u)
      return env({ removed: 1, meta: META })
    }
    if (u.endsWith('/meta')) return env(META)
    if (u.endsWith('/overview')) return env(OVERVIEW)
    return env({})
  })
}

function draw(fetchMock: ReturnType<typeof stubFetch>) {
  vi.stubGlobal('fetch', fetchMock)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  // Browse keeps the meta entry warm in production (status bar); seed it the
  // same way so the open transition reads lib as the default prefix.
  qc.setQueryData(['ontology', OID], META)
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <InstanceDialogs oid={OID} />
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useUiStore.setState({ instanceDialog: null, instanceJustCreated: null })
  useBrowseStore.setState({ selectedEid: null, revealEid: null })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('InstanceDialogs', () => {
  it('creates a minimal instance: POST body + reveal + just-created flag', async () => {
    const fetchMock = stubFetch()
    draw(fetchMock)
    useUiStore.getState().setInstanceDialog({ mode: 'create', parent: SF })
    const name = await screen.findByLabelText(/名称/)
    await userEvent.type(name, 'BallLightning')
    await userEvent.click(screen.getByRole('button', { name: /创建|保存/ }))

    await waitFor(() => expect(calls.post).toHaveLength(1))
    const { url, body } = calls.post[0]
    expect(url).toBe(`/api/ontologies/${OID}/instances`)
    // Menu context pre-picked the class; comment stays null when untouched.
    expect(body).toMatchObject({
      name: 'BallLightning',
      prefix: 'lib',
      classes: [SF],
      comment: null,
      baseFileHash: 'hash-3',
    })
    // Success reveals the fresh instance, flags it for the detail's
    // land-in-edit effect, and closes the dialog.
    expect(useBrowseStore.getState().revealEid).toBe(TB2)
    expect(useUiStore.getState().instanceJustCreated).toBe(TB2)
    await waitFor(() => expect(useUiStore.getState().instanceDialog).toBeNull())
  })

  it('shows an inline duplicate-name error and keeps the dialog open', async () => {
    const fetchMock = stubFetch({ dupOnPost: true })
    draw(fetchMock)
    useUiStore.getState().setInstanceDialog({ mode: 'create' })
    await userEvent.type(await screen.findByLabelText(/名称/), 'ThreeBody')
    await userEvent.click(screen.getByRole('button', { name: /创建|保存/ }))
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(useUiStore.getState().instanceDialog).not.toBeNull()
    expect(calls.del).toHaveLength(0)
  })

  it('delete confirms the local name, then DELETEs and clears the selection', async () => {
    const fetchMock = stubFetch()
    draw(fetchMock)
    useBrowseStore.setState({ selectedEid: TB2 })
    useUiStore.getState().setInstanceDialog({ mode: 'delete', eid: TB2 })
    await screen.findByText('删除实例')
    // The confirm line names the instance by its local curie name.
    expect(screen.getByText('BallLightning')).toBeTruthy()
    await userEvent.click(screen.getByRole('button', { name: '删除' }))

    await waitFor(() => expect(calls.del).toHaveLength(1))
    expect(calls.del[0]).toContain(`/api/ontologies/${OID}/instances/${encodeURIComponent(TB2)}`)
    expect(calls.del[0]).toContain('baseFileHash=hash-3')
    await waitFor(() => expect(useUiStore.getState().instanceDialog).toBeNull())
    expect(useBrowseStore.getState().selectedEid).toBeNull()
  })
})
