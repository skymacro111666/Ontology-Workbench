import { vi } from 'vitest'

/** G6 renders on canvas, which jsdom cannot provide. This mock replaces the
 *  Graph class so tests can assert on the data handed to the canvas
 *  (constructor options / setData / updateEdgeData) and fire canvas events
 *  through `handlers` (e.g. node:click).
 *
 *  Register from the test file (the factory import is hoist-safe):
 *    vi.mock('@antv/g6', async () => {
 *      const { MockGraph } = await import('../test/g6Mock')
 *      return { Graph: MockGraph }
 *    })
 */
export class MockGraph {
  options: Record<string, unknown>
  handlers: Record<string, (e: unknown) => void> = {}
  /** What getNodeData() returns when set (layout/drag results); falls back
   *  to the constructor data (which carries no coordinates in jsdom). */
  nodeData: { id: string; style?: Record<string, unknown> }[] = []
  /** Rendered coordinates per node id — mirrors G6 5.x, where drags update
   *  the element position and the data model's style.x stays stale.
   *  getElementPosition returns the real Point shape: a [x, y] tuple. */
  elementPositions: Record<string, { x: number; y: number }> = {}
  getElementPosition = vi.fn(function (this: MockGraph, id: string) {
    const p = this.elementPositions[id] ?? { x: 0, y: 0 }
    return [p.x, p.y] as [number, number]
  })
  render = vi.fn(async () => {})
  draw = vi.fn(async () => {})
  fitView = vi.fn(async () => {})
  focusElement = vi.fn(async () => {})
  zoomBy = vi.fn(async () => {})
  zoomTo = vi.fn(async () => {})
  getZoom = vi.fn(() => 1)
  setData = vi.fn()
  updateEdgeData = vi.fn()
  destroy = vi.fn()
  getNodeData = vi.fn(function (this: MockGraph) {
    return this.nodeData.length
      ? this.nodeData
      : ((this.options.data as { nodes?: unknown[] })?.nodes ?? [])
  })
  /** Every instance ever built in this test file (reset via `resetG6()`). */
  static instances: MockGraph[] = []
  constructor(options: Record<string, unknown>) {
    this.options = options
    MockGraph.instances.push(this)
  }
  on(event: string, handler: (e: unknown) => void) {
    this.handlers[event] = handler
  }
}

/** All mocked instances created so far in this test file. */
export const g6Instances = (): MockGraph[] => MockGraph.instances

/** The most recently built instance (the currently mounted GraphView). */
export const lastG6 = (): MockGraph | undefined => MockGraph.instances.at(-1)

/** Drop instance history between tests (vitest isolates files, not tests). */
export const resetG6 = (): void => {
  MockGraph.instances.length = 0
}

/** Stand-ins for the named exports GraphView consumes (mirrors the real
 *  module's surface; layout extensions are plain classes registered by name). */
export class BaseLayout {
  options: Record<string, unknown>
  constructor(_context: unknown, options?: Record<string, unknown>) {
    this.options = options ?? {}
  }
}

export const register = vi.fn()

export const ExtensionCategory = {
  BEHAVIOR: 'behavior',
  COMBO: 'combo',
  EDGE: 'edge',
  LAYOUT: 'layout',
  NODE: 'node',
  PLUGIN: 'plugin',
  TRANSFORM: 'transform',
} as const
