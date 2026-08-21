import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ClassTree from './ClassTree'
import { useBrowseStore } from '../stores/browseStore'
import type { Envelope, TreeNode } from '../api/types'

const THING = 'http://example.org/Thing'
const ANIMAL = 'http://example.org/Animal'

function node(eid: string, curie: string, childrenCount: number, type = 'Class'): TreeNode {
  return { eid, curie, label: {}, type, childrenCount }
}

/** Route /tree calls: bare = roots, ?parent= = children of Thing. */
function stubTreeFetch() {
  return vi.fn(async (url: string | URL) => {
    const u = String(url)
    let data: TreeNode[]
    if (u.includes(`parent=${encodeURIComponent(THING)}`)) {
      data = [node(ANIMAL, 'ex:Animal', 1)]
    } else {
      data = [node(THING, 'ex:Thing', 1), node('http://example.org/Solo', 'ex:Solo', 0)]
    }
    return new Response(
      JSON.stringify({ code: 'OK', message: 'ok', data, hint: null, request_id: 'r' } satisfies Envelope<TreeNode[]>),
      { headers: { 'Content-Type': 'application/json' } },
    )
  })
}

function renderTree(fetchMock: ReturnType<typeof stubTreeFetch>) {
  vi.stubGlobal('fetch', fetchMock)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const { container } = render(
    <QueryClientProvider client={qc}>
      <ClassTree oid="oid-1" />
    </QueryClientProvider>,
  )
  return container
}

beforeEach(() => {
  useBrowseStore.setState({ selectedEid: null, viewMode: 'detail' })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('ClassTree', () => {
  it('loads the roots from /tree and renders their CURIEs', async () => {
    const fetchMock = stubTreeFetch()
    renderTree(fetchMock)
    expect(await screen.findByText('ex:Thing')).toBeTruthy()
    expect(screen.getByText('ex:Solo')).toBeTruthy()
    expect(fetchMock).toHaveBeenCalledWith('/api/ontologies/oid-1/tree', expect.anything())
  })

  it('lazily loads children on expand and publishes selection to the store', async () => {
    const fetchMock = stubTreeFetch()
    const container = renderTree(fetchMock)
    expect(await screen.findByText('ex:Thing')).toBeTruthy()

    // Expand via the switcher: AntD fires loadData for non-leaf nodes.
    const switcher = container.querySelector('.ant-tree-switcher')
    expect(switcher).toBeTruthy()
    await userEvent.click(switcher as HTMLElement)

    expect(await screen.findByText('ex:Animal')).toBeTruthy()
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/ontologies/oid-1/tree?parent=${encodeURIComponent(THING)}`,
      expect.anything(),
    )

    // Selecting a node updates the shared browse store.
    await userEvent.click(screen.getByText('ex:Animal'))
    await waitFor(() => expect(useBrowseStore.getState().selectedEid).toBe(ANIMAL))
  })
})
