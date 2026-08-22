import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ClassTree from './ClassTree'
import { useBrowseStore } from '../stores/browseStore'
import type { Envelope, OntologyMeta, TreeNode } from '../api/types'

const THING = 'http://example.org/Thing'
const ANIMAL = 'http://example.org/Animal'

function node(eid: string, curie: string, childrenCount: number, type = 'Class'): TreeNode {
  return { eid, curie, label: {}, type, childrenCount }
}

function ok(data: unknown) {
  return new Response(
    JSON.stringify({ code: 'OK', message: 'ok', data, hint: null, request_id: 'r' } satisfies Envelope<unknown>),
    { headers: { 'Content-Type': 'application/json' } },
  )
}

const META: OntologyMeta = {
  id: 'oid-1',
  title: 'Pizza',
  filename: 'pizza.ttl',
  format: 'turtle',
  classCount: 2,
  propertyCount: 2,
  axiomCount: 10,
  fileSizeBytes: 1024,
  createdAt: '2026-01-01T00:00:00Z',
  fileHash: 'h',
  prefixes: { owl: 'http://www.w3.org/2002/07/owl#', ex: 'http://example.org/' },
}

/** Route the tree's four endpoints: roots, children, __props__, meta. */
function stubFetch() {
  return vi.fn(async (url: string | URL) => {
    const u = String(url)
    if (u.endsWith('/meta')) return ok(META)
    if (u.includes('parent=__props__')) {
      return ok([
        node('http://example.org/hasTopping', 'ex:hasTopping', 0, 'ObjectProperty'),
        node('http://example.org/hasName', 'ex:hasName', 0, 'DatatypeProperty'),
      ])
    }
    if (u.includes(`parent=${encodeURIComponent(THING)}`)) {
      return ok([node(ANIMAL, 'ex:Animal', 1)])
    }
    if (u.endsWith('/tree')) {
      return ok([node(THING, 'ex:Thing', 1), node('http://example.org/Solo', 'ex:Solo', 0)])
    }
    throw new Error(`unmocked url: ${u}`)
  })
}

function renderTree(fetchMock: ReturnType<typeof stubFetch>) {
  vi.stubGlobal('fetch', fetchMock)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <ClassTree oid="oid-1" />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useBrowseStore.setState({ selectedEid: null, viewMode: 'detail', revealEid: null })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('ClassTree', () => {
  it('renders the roots with direct-subclass badges', async () => {
    const fetchMock = stubFetch()
    renderTree(fetchMock)
    expect(await screen.findByText('ex:Thing')).toBeTruthy()
    expect(screen.getByText('ex:Solo')).toBeTruthy()
    // Thing has one child; Solo none, so exactly one badge shows.
    expect(screen.getByTitle('直接子类数').textContent).toBe('1')
    expect(fetchMock).toHaveBeenCalledWith('/api/ontologies/oid-1/tree', expect.anything())
  })

  it('lazily loads children on expand and publishes selection to the store', async () => {
    const fetchMock = stubFetch()
    renderTree(fetchMock)
    expect(await screen.findByText('ex:Thing')).toBeTruthy()

    await userEvent.click(screen.getByRole('button', { name: '展开' }))

    expect(await screen.findByText('ex:Animal')).toBeTruthy()
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/ontologies/oid-1/tree?parent=${encodeURIComponent(THING)}`,
      expect.anything(),
    )

    // Clicking a row updates the shared browse store.
    await userEvent.click(screen.getByText('ex:Animal'))
    await waitFor(() => expect(useBrowseStore.getState().selectedEid).toBe(ANIMAL))
  })

  it('marks the store-selected row as selected', async () => {
    useBrowseStore.setState({ selectedEid: THING })
    renderTree(stubFetch())
    expect(await screen.findByText('ex:Thing')).toBeTruthy()
    const row = screen.getByText('ex:Thing').closest('[role="treeitem"]')
    expect(row?.getAttribute('aria-selected')).toBe('true')
    // The highlight lives on the row content inside the treeitem wrapper.
    expect(row?.querySelector('.bg-primary-soft')).toBeTruthy()
  })

  it('filters loaded nodes case-insensitively from the top search box', async () => {
    renderTree(stubFetch())
    expect(await screen.findByText('ex:Thing')).toBeTruthy()
    expect(screen.getByText('ex:Solo')).toBeTruthy()

    await userEvent.type(screen.getByPlaceholderText('过滤已加载节点'), 'THING')

    await waitFor(() => expect(screen.queryByText('ex:Solo')).toBeNull())
    expect(screen.getByText('ex:Thing')).toBeTruthy()
  })

  it('lists properties on the __props__ tab', async () => {
    const fetchMock = stubFetch()
    renderTree(fetchMock)
    expect(await screen.findByText('ex:Thing')).toBeTruthy()

    await userEvent.click(screen.getByRole('tab', { name: '属性' }))

    expect(await screen.findByText('ex:hasTopping')).toBeTruthy()
    expect(screen.getByText('ex:hasName')).toBeTruthy()
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/ontologies/oid-1/tree?parent=__props__',
      expect.anything(),
    )
  })

  it('renders the prefix table from ontology meta', async () => {
    const fetchMock = stubFetch()
    renderTree(fetchMock)
    expect(await screen.findByText('ex:Thing')).toBeTruthy()

    await userEvent.click(screen.getByRole('tab', { name: '前缀' }))

    expect(await screen.findByText('owl')).toBeTruthy()
    expect(screen.getByText('http://www.w3.org/2002/07/owl#')).toBeTruthy()
    expect(fetchMock).toHaveBeenCalledWith('/api/ontologies/oid-1/meta', expect.anything())
  })
})
