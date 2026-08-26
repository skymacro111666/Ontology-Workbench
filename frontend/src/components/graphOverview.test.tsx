import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Envelope, NodesEdges } from '../api/types'
import { useUiStore } from '../stores/uiStore'
import { ThemeProvider } from '../theme/ThemeProvider'
import { lastG6, resetG6 } from '../test/g6Mock'
import GraphOverview from './GraphOverview'

/* The overview owns the layout query: it waits for GET /layout before
   mounting the canvas, PUTs the debounced drag map, and the 重排 button
   DELETEs the row so the next mount returns to the auto pipeline. */

vi.mock('@antv/g6', async () => {
  const mock = await import('../test/g6Mock')
  return {
    Graph: mock.MockGraph,
    BaseLayout: mock.BaseLayout,
    register: mock.register,
    ExtensionCategory: mock.ExtensionCategory,
  }
})

const OVERVIEW: NodesEdges = {
  nodes: [{ id: 'a', curie: 'ex:A', label: {}, kind: 'class' }],
  edges: [],
  truncated: false,
  totalCount: 1,
}

function env(data: unknown) {
  return new Response(
    JSON.stringify({ code: 'OK', message: 'ok', data, hint: null, request_id: 'r' } satisfies Envelope<unknown>),
    { headers: { 'Content-Type': 'application/json' } },
  )
}

let savedBody: { positions: Record<string, { x: number; y: number }> } | undefined

function stubFetch(layout: Record<string, { x: number; y: number }> | null = null) {
  return vi.fn(async (url: string | URL, init?: RequestInit) => {
    const u = String(url)
    if (u.endsWith('/overview')) return env(OVERVIEW)
    if (u.endsWith('/layout') && init?.method === 'PUT') {
      savedBody = JSON.parse(String(init.body))
      return env(savedBody)
    }
    return env({ positions: layout ?? {} })
  })
}

function draw(fetchMock: ReturnType<typeof stubFetch>) {
  vi.stubGlobal('fetch', fetchMock)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <GraphOverview oid="oid-1" />
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  resetG6()
  savedBody = undefined
  useUiStore.setState({ entityDialog: null })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('GraphOverview layout persistence', () => {
  it('mounts the canvas with the auto pipeline when nothing is saved', async () => {
    draw(stubFetch())
    await waitForGraph()
    expect(Array.isArray(lastG6()!.options.layout)).toBe(true)
  })

  it('switches the canvas off the auto pipeline when positions are saved', async () => {
    draw(stubFetch({ a: { x: 5, y: 6 } }))
    await waitForGraph()
    expect(lastG6()!.options.layout).toBe(false)
  })

  it('PUTs the debounced drag map to /layout', async () => {
    vi.useFakeTimers()
    try {
      draw(stubFetch())
      await waitForGraph()
      const g = lastG6()!
      g.nodeData = [{ id: 'a', style: { x: 42, y: 43 } }]
      g.handlers['node:dragend']({})
      vi.advanceTimersByTime(800)
      await vi.advanceTimersByTimeAsync(0)
      expect(savedBody?.positions).toEqual({ a: { x: 42, y: 43 } })
    } finally {
      vi.useRealTimers()
    }
  })

  it('重排 DELETEs the row and remounts onto the auto pipeline', async () => {
    const fetchMock = stubFetch({ a: { x: 5, y: 6 } })
    draw(fetchMock)
    await waitForGraph()
    expect(lastG6()!.options.layout).toBe(false)
    await userEvent.click(screen.getByText('重排'))
    await waitForGraph()
    expect(Array.isArray(lastG6()!.options.layout)).toBe(true)
    expect(fetchMock.mock.calls.some(([u, i]) => String(u).endsWith('/layout') && i?.method === 'DELETE')).toBe(
      true,
    )
  })
})

describe('GraphOverview context menu', () => {
  it('opens create menu on blank right-click and routes 新建子类 to the store', async () => {
    draw(stubFetch())
    await waitForGraph()
    const g = lastG6()!
    g.handlers['canvas:contextmenu']({ client: { x: 10, y: 12 }, preventDefault: vi.fn() })
    expect(await screen.findByRole('menu')).toBeTruthy()
    expect(screen.getByText('＋ 新建类')).toBeTruthy()
    expect(screen.getByText('＋ 新建对象属性')).toBeTruthy()

    g.handlers['node:contextmenu']({
      target: { id: 'a' },
      originalTarget: null,
      client: { x: 10, y: 12 },
      preventDefault: vi.fn(),
    })
    await screen.findByText('新建子类')
    await userEvent.click(screen.getByText('新建子类'))
    expect(useUiStore.getState().entityDialog).toEqual({
      mode: 'subclass',
      parent: 'a',
    })
  })
})

function waitForGraph() {
  return vi.waitFor(() => {
    if (!lastG6()) throw new Error('graph not mounted yet')
  })
}
