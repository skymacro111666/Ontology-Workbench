import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ClassTree from './ClassTree'
import { useBrowseStore } from '../stores/browseStore'
import type { Envelope, OntologyMeta, TreeNode } from '../api/types'

const THING = 'http://example.org/Thing'
const ANIMAL = 'http://example.org/Animal'

function node(
  eid: string,
  curie: string,
  childrenCount: number,
  type = 'Class',
  instanceCount = 0,
): TreeNode {
  return { eid, curie, label: {}, type, childrenCount, instanceCount }
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
  instanceCount: 0,
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
      return ok([
        node(THING, 'ex:Thing', 1, 'Class', 3),
        node('http://example.org/Solo', 'ex:Solo', 0),
        // Unbound-namespace fallback: _curie returns the full IRI.
        node('http://fallback.example/Odd', 'http://fallback.example/Odd', 0),
      ])
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
  useBrowseStore.setState({ selectedEid: null, revealEid: null })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('ClassTree', () => {
  it('renders the roots with instance-count badges', async () => {
    const fetchMock = stubFetch()
    renderTree(fetchMock)
    expect(await screen.findByText('Thing')).toBeTruthy()
    expect(screen.getByText('Solo')).toBeTruthy()
    // Thing has 3 instances; Solo none, so exactly one badge shows.
    const badge = screen.getByTitle('实例数')
    expect(badge.textContent).toBe('3')
    // The badge stands out with a solid primary background (canvas-consistent).
    expect(badge.className.split(/\s+/)).toContain('bg-primary')
    expect(badge.className.split(/\s+/)).toContain('text-primary-foreground')
    // Class rows carry no property-kind pill.
    expect(screen.queryByText('OP')).toBeNull()
    expect(screen.queryByText('DP')).toBeNull()
    expect(fetchMock).toHaveBeenCalledWith('/api/ontologies/oid-1/tree', expect.anything())
  })

  it('shows local names (prefix stripped), full curie kept on the tooltip', async () => {
    renderTree(stubFetch())
    const name = await screen.findByText('Thing')
    // Tooltip carries the full curie for disambiguation.
    expect(name.title).toBe('ex:Thing')
    // Unbound-namespace curie (full IRI fallback) reduces to its last segment.
    const odd = screen.getByText('Odd')
    expect(odd.title).toBe('http://fallback.example/Odd')
  })

  it('lazily loads children on expand and publishes selection to the store', async () => {
    const fetchMock = stubFetch()
    renderTree(fetchMock)
    expect(await screen.findByText('Thing')).toBeTruthy()

    await userEvent.click(screen.getByRole('button', { name: '展开' }))

    expect(await screen.findByText('Animal')).toBeTruthy()
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/ontologies/oid-1/tree?parent=${encodeURIComponent(THING)}`,
      expect.anything(),
    )

    // Clicking a row updates the shared browse store.
    await userEvent.click(screen.getByText('Animal'))
    await waitFor(() => expect(useBrowseStore.getState().selectedEid).toBe(ANIMAL))
  })

  it('keeps the tree usable when expanding a node fails (no unhandled rejection)', async () => {
    // handleToggle voids loadChildren; without a catch the rejection goes
    // unhandled (backlog T10①). The tree must simply not expand.
    const fetchMock = stubFetch()
    fetchMock.mockImplementation(async (url: string | URL) => {
      const u = String(url)
      if (u.includes(`parent=${encodeURIComponent(THING)}`)) {
        throw new TypeError('network down')
      }
      return stubFetch().getMockImplementation()!(url)
    })
    renderTree(fetchMock)
    expect(await screen.findByText('Thing')).toBeTruthy()

    await userEvent.click(screen.getByRole('button', { name: '展开' }))
    // Let the rejection land; the roots stay interactive afterwards.
    await new Promise((r) => setTimeout(r, 50))
    expect(screen.getByText('Thing')).toBeTruthy()
    expect(screen.queryByText('Animal')).toBeNull()
  })

  it('reveal walk loads each ancestor level and lands on the target (backlog T10②)', async () => {
    // Dog ← Animal ← Thing: the walk must fetch each /entities parent,
    // materialize every tree level top-down, then select Dog.
    const DOG = 'http://example.org/Dog'
    const curieOf = (eid: string) => `ex:${eid.split('/').pop()}`
    const parentOf: Record<string, string | null> = { [DOG]: ANIMAL, [ANIMAL]: THING, [THING]: null }
    const fetchMock = vi.fn(async (url: string | URL) => {
      const u = String(url)
      if (u.endsWith('/meta')) return ok(META)
      if (u.includes('/entities/')) {
        const eid = decodeURIComponent(u.split('/entities/')[1])
        const p = parentOf[eid]
        return ok({
          eid,
          curie: curieOf(eid),
          label: {},
          parents: p ? [{ eid: p, curie: curieOf(p), label: {} }] : [],
        })
      }
      if (u.includes(`parent=${encodeURIComponent(THING)}`)) return ok([node(ANIMAL, 'ex:Animal', 1)])
      if (u.includes(`parent=${encodeURIComponent(ANIMAL)}`)) return ok([node(DOG, 'ex:Dog', 0)])
      if (u.includes(`parent=${encodeURIComponent(DOG)}`)) return ok([])
      if (u.endsWith('/tree')) return ok([node(THING, 'ex:Thing', 1, 'Class', 3)])
      throw new Error(`unmocked url: ${u}`)
    })
    renderTree(fetchMock as unknown as ReturnType<typeof stubFetch>)
    expect(await screen.findByText('Thing')).toBeTruthy()

    act(() => useBrowseStore.getState().reveal(DOG))

    expect(await screen.findByText('Dog')).toBeTruthy()
    await waitFor(() => expect(useBrowseStore.getState().selectedEid).toBe(DOG))
    await waitFor(() => expect(useBrowseStore.getState().revealEid).toBeNull())
  })

  it('marks the store-selected row as selected', async () => {
    useBrowseStore.setState({ selectedEid: THING })
    renderTree(stubFetch())
    expect(await screen.findByText('Thing')).toBeTruthy()
    const row = screen.getByText('Thing').closest('[role="treeitem"]')
    expect(row?.getAttribute('aria-selected')).toBe('true')
    // The highlight lives on the row content inside the treeitem wrapper.
    expect(row?.querySelector('.bg-primary-soft')).toBeTruthy()
  })

  it('filters loaded nodes case-insensitively from the top search box', async () => {
    renderTree(stubFetch())
    expect(await screen.findByText('Thing')).toBeTruthy()
    expect(screen.getByText('Solo')).toBeTruthy()

    // Search still matches the full curie, though rows display local names.
    await userEvent.type(screen.getByPlaceholderText('搜索类 / 属性 / 注释…'), 'THING')

    await waitFor(() => expect(screen.queryByText('Solo')).toBeNull())
    expect(screen.getByText('Thing')).toBeTruthy()
  })

  it('lists properties on the __props__ tab, OP/DP kind pills after the name', async () => {
    const fetchMock = stubFetch()
    renderTree(fetchMock)
    expect(await screen.findByText('Thing')).toBeTruthy()

    await userEvent.click(screen.getByRole('button', { name: '属性' }))

    expect(await screen.findByText('hasTopping')).toBeTruthy()
    expect(screen.getByText('hasName')).toBeTruthy()
    // Object vs datatype properties tag apart (OP primary, DP neutral).
    expect(screen.getByText('OP').className).toContain('text-primary')
    expect(screen.getByText('DP').className).toContain('text-ink-2')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/ontologies/oid-1/tree?parent=__props__',
      expect.anything(),
    )
  })

  it('renders the prefix table from ontology meta', async () => {
    const fetchMock = stubFetch()
    renderTree(fetchMock)
    expect(await screen.findByText('Thing')).toBeTruthy()

    await userEvent.click(screen.getByRole('button', { name: '命名空间' }))

    expect(await screen.findByText('owl')).toBeTruthy()
    expect(screen.getByText('http://www.w3.org/2002/07/owl#')).toBeTruthy()
    expect(fetchMock).toHaveBeenCalledWith('/api/ontologies/oid-1/meta', expect.anything())
  })
})
