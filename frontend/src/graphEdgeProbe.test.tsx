/* One-shot diagnostic probe: does GraphView render edge paths at all?
   Deleted after the investigation. */
import { cleanup, render } from '@testing-library/react'
import { ReactFlow } from '@xyflow/react'
import { afterEach, describe, it } from 'vitest'
import GraphView from './components/GraphView'
import { ThemeProvider } from './theme/ThemeProvider'

afterEach(() => cleanup())

describe('edge render probe', () => {
  it('bare ReactFlow: two nodes, one edge', async () => {
    render(
      <ReactFlow
        nodes={[
          { id: 'a', position: { x: 0, y: 0 }, data: { label: 'A' } },
          { id: 'b', position: { x: 200, y: 100 }, data: { label: 'B' } },
        ]}
        edges={[{ id: 'e1', source: 'a', target: 'b' }]}
        fitView
      />,
    )
    await new Promise((r) => setTimeout(r, 400))
    throw new Error(
      `PROBE-BARE → edge elements: ${document.querySelectorAll('.react-flow__edge').length}, paths: ${document.querySelectorAll('.react-flow__edge path').length}, nodes: ${document.querySelectorAll('.react-flow__node').length}`,
    )
  })

  it('counts react-flow edge paths with measuring ResizeObserver', async () => {
    // A ResizeObserver that actually reports a size, so React Flow can
    // measure nodes (the setup stub never fires, so nothing is ever measured).
    class MeasuringRO {
      observe(el: Element) {
        queueMicrotask(() => {
          el.dispatchEvent(new Event('resize'))
          ;(this.cb as (entries: ResizeObserverEntry[]) => void)([
            { target: el, contentRect: { width: 120, height: 36 } },
          ] as ResizeObserverEntry[])
        })
      }
      unobserve() {}
      disconnect() {}
      constructor(private cb: ResizeObserverCallback) {}
    }
    const saved = globalThis.ResizeObserver
    globalThis.ResizeObserver = MeasuringRO as unknown as typeof ResizeObserver

    render(
      <ThemeProvider>
        <GraphView
          nodes={[
            { id: 'http://ex/A', curie: ':A', label: {}, kind: 'class' },
            { id: 'http://ex/B', curie: ':B', label: {}, kind: 'class' },
          ]}
          edges={[{ source: 'http://ex/A', target: 'http://ex/B', kind: 'subClassOf' }]}
        />
      </ThemeProvider>,
    )

    await new Promise((r) => setTimeout(r, 500))
    globalThis.ResizeObserver = saved

    const edgeEls = document.querySelectorAll('.react-flow__edge')
    const paths = document.querySelectorAll('.react-flow__edge path')
    const nodeEls = document.querySelectorAll('.react-flow__node')
    const stroke = paths[0]?.getAttribute('style') ?? paths[0]?.getAttribute('stroke') ?? 'no-path'
    throw new Error(
      `PROBE2 → edge elements: ${edgeEls.length}, edge paths: ${paths.length}, node elements: ${nodeEls.length}, first path style: ${stroke}`,
    )
  })
})
