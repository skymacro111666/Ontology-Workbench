import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import GraphView, { toFlowEdges, type GraphViewNode } from './GraphView'
import type { GEdge } from '../api/types'

const NODES: GraphViewNode[] = [
  { id: 'a', curie: 'ex:A', label: {}, kind: 'class', childCount: 2, highlighted: true },
  { id: 'b', curie: 'ex:B', label: {}, kind: 'class' },
  { id: 'p', curie: 'ex:hasTopping', label: {}, kind: 'property' },
]

const EDGES: GEdge[] = [
  { source: 'b', target: 'a', kind: 'subClassOf' },
  { source: 'a', target: 'p', kind: 'property' },
]

afterEach(() => {
  cleanup()
})

describe('GraphView', () => {
  it('renders every node with the subclass badge', async () => {
    render(<GraphView nodes={NODES} edges={EDGES} onSelect={vi.fn()} />)
    expect(await screen.findByText('ex:A')).toBeTruthy()
    expect(screen.getByText('ex:B')).toBeTruthy()
    expect(screen.getByText('ex:hasTopping')).toBeTruthy()
    // Badge carries the direct-subclass count.
    expect(screen.getByText('2')).toBeTruthy()
  })

  it('toggles the label button state off and back on', async () => {
    render(<GraphView nodes={NODES} edges={EDGES} onSelect={vi.fn()} />)
    // AntD auto-inserts a space between two-CJK-char button labels (标 签).
    const btn = await screen.findByRole('button', { name: /标\s*签/ })
    expect(btn.getAttribute('aria-pressed')).toBe('true')
    await userEvent.click(btn)
    expect(btn.getAttribute('aria-pressed')).toBe('false')
    await userEvent.click(btn)
    expect(btn.getAttribute('aria-pressed')).toBe('true')
  })

  it('filters to properties only and back to all', async () => {
    const onSelect = vi.fn()
    render(<GraphView nodes={NODES} edges={EDGES} onSelect={onSelect} />)
    expect(await screen.findByText('ex:A')).toBeTruthy()
    // Segmented control: only property nodes remain.
    await userEvent.click(screen.getByText('仅属性'))
    expect(screen.queryByText('ex:A')).toBeNull()
    expect(screen.queryByText('ex:B')).toBeNull()
    expect(screen.getByText('ex:hasTopping')).toBeTruthy()
    await userEvent.click(screen.getByText('全部'))
    expect(screen.getByText('ex:A')).toBeTruthy()
  })

  it('classes-only filter keeps classes and drops the property node', async () => {
    render(<GraphView nodes={NODES} edges={EDGES} onSelect={vi.fn()} />)
    expect(await screen.findByText('ex:hasTopping'))
    await userEvent.click(screen.getByText('仅类'))
    expect(screen.getByText('ex:A')).toBeTruthy()
    expect(screen.getByText('ex:B')).toBeTruthy()
    expect(screen.queryByText('ex:hasTopping')).toBeNull()
  })
})

describe('toFlowEdges', () => {
  // React Flow edge labels do not paint in jsdom (no measured dimensions);
  // the mapping itself is covered here.
  const all = new Set(['a', 'b', 'p'])

  it('labels edges with their kind and encodes semantics', () => {
    const flow = toFlowEdges(EDGES, all, true)
    expect(flow.map((e) => e.label)).toEqual(['subClassOf', 'property'])
    expect(flow[0].style).toMatchObject({ stroke: '#8B5CF6', strokeDasharray: '6 4' })
    expect(flow[1].style).toMatchObject({ stroke: '#0D9488' })
    expect(flow[1].style?.strokeDasharray).toBeUndefined()
  })

  it('drops labels when disabled and hides edges to filtered-out nodes', () => {
    expect(toFlowEdges(EDGES, all, false).every((e) => e.label === undefined)).toBe(true)
    const classesOnly = new Set(['a', 'b'])
    const flow = toFlowEdges(EDGES, classesOnly, true)
    expect(flow).toHaveLength(1) // class-property edge hidden
    expect(flow[0].label).toBe('subClassOf')
  })
})
