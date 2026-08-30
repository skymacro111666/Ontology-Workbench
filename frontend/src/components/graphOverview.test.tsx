import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { toast } from 'sonner'
import { Toaster } from './ui/sonner'
import type { Envelope, NodesEdges } from '../api/types'
import { useBrowseStore } from '../stores/browseStore'
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

/** Truncated variant: same canvas content, but flagged as cut off. */
const TRUNCATED_OVERVIEW: NodesEdges = { ...OVERVIEW, truncated: true }

function env(data: unknown) {
  return new Response(
    JSON.stringify({ code: 'OK', message: 'ok', data, hint: null, request_id: 'r' } satisfies Envelope<unknown>),
    { headers: { 'Content-Type': 'application/json' } },
  )
}

let savedBody: { positions: Record<string, { x: number; y: number }> } | undefined

function stubFetch(
  layout: Record<string, { x: number; y: number }> | null = null,
  overview: NodesEdges = OVERVIEW,
) {
  return vi.fn(async (url: string | URL, init?: RequestInit) => {
    const u = String(url)
    if (u.endsWith('/overview')) return env(overview)
    if (u.endsWith('/layout') && init?.method === 'PUT') {
      savedBody = JSON.parse(String(init.body))
      return env(savedBody)
    }
    return env({ positions: layout ?? {} })
  })
}

function draw(fetchMock: ReturnType<typeof stubFetch>, focus?: string) {
  vi.stubGlobal('fetch', fetchMock)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <Toaster />
        <GraphOverview oid="oid-1" focus={focus} />
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  resetG6()
  savedBody = undefined
  useUiStore.setState({ entityDialog: null, instanceDialog: null })
  useBrowseStore.setState({ selectedEid: null, revealEid: null })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  // Sonner keeps toasts in a module-global store that outlives unmounting;
  // drop them so a prior test's toast cannot leak into the next Toaster.
  toast.dismiss()
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
      g.elementPositions = { a: { x: 42, y: 43 } }
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

describe('GraphOverview focus feedback', () => {
  it('stays quiet when the focus entity is present', async () => {
    draw(stubFetch(null, TRUNCATED_OVERVIEW), 'a')
    // Give the settled data a moment; no toast may appear.
    await new Promise((r) => setTimeout(r, 100))
    expect(screen.queryByText(/未出现在总览中/)).toBeNull()
  })

  it('stays quiet when the overview is not truncated (inspector covers dead links)', async () => {
    draw(stubFetch(null, OVERVIEW), 'http://example.org/Ghost')
    await new Promise((r) => setTimeout(r, 100))
    expect(screen.queryByText(/未出现在总览中/)).toBeNull()
  })

  it('notifies when the focus entity is cut off by a truncated overview', async () => {
    // Deep link ?focus=… pointing outside the truncated overview must not
    // degrade silently (backlog T12①).
    draw(stubFetch(null, TRUNCATED_OVERVIEW), 'http://example.org/Ghost')
    await waitFor(() => expect(screen.getByText(/未出现在总览中/)).toBeTruthy())
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
    // Blank-canvas menu offers classes only (2026-08-27 user call).
    expect(screen.queryByText('＋ 新建对象属性')).toBeNull()

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

  it('class menu offers 添加实例; instance nodes get 编辑实例/删除实例 (B2)', async () => {
    const overview: NodesEdges = {
      nodes: [
        { id: 'a', curie: 'ex:A', label: {}, kind: 'class' },
        { id: 'i1', curie: 'ex:Inst', label: {}, kind: 'instance' },
      ],
      edges: [],
      truncated: false,
      totalCount: 2,
    }
    draw(stubFetch(null, overview))
    await waitForGraph()
    const g = lastG6()!
    const rightClick = (id: string) =>
      g.handlers['node:contextmenu']({
        target: { id },
        originalTarget: null,
        client: { x: 10, y: 12 },
        preventDefault: vi.fn(),
      })

    // Class menu: 添加实例 pre-fills the create dialog with the class eid.
    rightClick('a')
    await userEvent.click(await screen.findByText('添加实例'))
    expect(useUiStore.getState().instanceDialog).toEqual({ mode: 'create', parent: 'a' })

    // Instance node: 编辑实例 reveals (select + focus); 删除实例 opens the
    // delete dialog with the instance's local name in the label.
    rightClick('i1')
    await userEvent.click(await screen.findByText('编辑实例'))
    expect(useBrowseStore.getState().selectedEid).toBe('i1')
    expect(useBrowseStore.getState().revealEid).toBe('i1')
    rightClick('i1')
    await userEvent.click(await screen.findByText('删除 Inst'))
    expect(useUiStore.getState().instanceDialog).toEqual({ mode: 'delete', eid: 'i1' })
  })
})

function waitForGraph() {
  return vi.waitFor(() => {
    if (!lastG6()) throw new Error('graph not mounted yet')
  })
}
