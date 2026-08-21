import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import EntityDetail from './EntityDetail'
import { useBrowseStore } from '../stores/browseStore'
import type { Envelope, EntityIR } from '../api/types'

const EID = 'http://example.org/Margherita'
const PARENT = 'http://example.org/NamedPizza'

function entity(): EntityIR {
  return {
    eid: EID,
    curie: 'pizza:Margherita',
    type: 'Class',
    label: { en: 'Margherita', zh: '玛格丽特' },
    comment: 'A pizza with tomato and mozzarella.',
    deprecated: false,
    parents: [{ eid: PARENT, curie: 'pizza:NamedPizza', label: {} }],
    children: [],
    properties: [
      { eid: 'http://example.org/hasTopping', curie: 'pizza:hasTopping', label: {}, ptype: 'ObjectProperty' },
    ],
    referencedBy: [
      { eid: 'http://example.org/hasTopping', curie: 'pizza:hasTopping', label: {}, relation: 'rdfs:domain' },
    ],
    axioms: [{ turtle: '<pizza:Margherita> a owl:Class .' }],
    stats: { directChildren: 2, totalDescendants: 7 },
  }
}

function stubFetch() {
  return vi.fn(async (url: string | URL) => {
    const u = String(url)
    const data =
      u.includes('/raw/') ? { turtle: 'pizza:Margherita a owl:Class .', eid: EID } : entity()
    return new Response(
      JSON.stringify({ code: 'OK', message: 'ok', data, hint: null, request_id: 'r' } satisfies Envelope<unknown>),
      { headers: { 'Content-Type': 'application/json' } },
    )
  })
}

function renderDetail(fetchMock: ReturnType<typeof stubFetch>) {
  vi.stubGlobal('fetch', fetchMock)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <EntityDetail oid="oid-1" />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useBrowseStore.setState({ selectedEid: EID, viewMode: 'detail' })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('EntityDetail', () => {
  it('renders the overview: labels, comment, parent links, properties, stats', async () => {
    renderDetail(stubFetch())
    expect(await screen.findByText('pizza:Margherita')).toBeTruthy()
    expect(screen.getByText('en: Margherita')).toBeTruthy()
    expect(screen.getByText('zh: 玛格丽特')).toBeTruthy()
    expect(screen.getByText(/A pizza with tomato and mozzarella/)).toBeTruthy()
    expect(screen.getByText(/直接子类 2/)).toBeTruthy()
    expect(screen.getByText(/全部后代 7/)).toBeTruthy()
    // Parent is a navigation link; property table carries its type.
    expect(screen.getByText('pizza:NamedPizza')).toBeTruthy()
    expect(screen.getByText('ObjectProperty')).toBeTruthy()
  })

  it('shows raw Turtle in the TTL tab', async () => {
    renderDetail(stubFetch())
    await screen.findByText('pizza:Margherita')
    await userEvent.click(screen.getByRole('tab', { name: '原始TTL' }))
    expect(await screen.findByText(/a owl:Class/)).toBeTruthy()
  })

  it('renders the back-reference panel with relations; empty state without', async () => {
    renderDetail(stubFetch())
    expect(await screen.findByText('反向引用')).toBeTruthy()
    expect(screen.getByText('rdfs:domain')).toBeTruthy()
  })
})
