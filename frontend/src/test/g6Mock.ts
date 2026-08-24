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
  render = vi.fn(async () => {})
  draw = vi.fn(async () => {})
  fitView = vi.fn(async () => {})
  focusElement = vi.fn(async () => {})
  zoomBy = vi.fn(async () => {})
  getZoom = vi.fn(() => 1)
  setData = vi.fn()
  updateEdgeData = vi.fn()
  destroy = vi.fn()
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
