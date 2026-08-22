import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import EntityDetail from './EntityDetail'
import { useBrowseStore } from '../stores/browseStore'
import type { Envelope, EntityIR } from '../api/types'

const EID = 'http://example.org/Dog'
const PARENT = 'http://example.org/Animal'

/** Same shape as entity() in browse.test.tsx, extended with
 *  children/properties/referencedBy entries so every overview section renders. */
function entity(): EntityIR {
  return {
    eid: EID,
    curie: 'pizza:Dog',
    type: 'Class',
    label: { en: 'Dog' },
    comment: null,
    deprecated: false,
    parents: [{ eid: PARENT, curie: 'pizza:Animal', label: {} }],
    children: [{ eid: 'http://example.org/Corgi', curie: 'pizza:Corgi', label: {} }],
    properties: [
      {
        eid: 'http://example.org/hasOwner',
        curie: 'pizza:hasOwner',
        label: {},
        ptype: 'ObjectProperty',
      },
    ],
    referencedBy: [
      {
        eid: 'http://example.org/Kennel',
        curie: 'pizza:Kennel',
        label: {},
        relation: 'rdfs:domain',
      },
    ],
    axioms: [{ turtle: 'x' }],
    stats: { directChildren: 2, totalDescendants: 7 },
  }
}

function stubFetch(data: EntityIR = entity()) {
  return vi.fn(async (url: string | URL) => {
    const u = String(url)
    const body =
      u.includes('/raw/') ? { turtle: 'pizza:Dog a owl:Class .', eid: EID } : data
    return new Response(
      JSON.stringify({ code: 'OK', message: 'ok', data: body, hint: null, request_id: 'r' } satisfies Envelope<unknown>),
      { headers: { 'Content-Type': 'application/json' } },
    )
  })
}

function renderDetail(fetchMock: ReturnType<typeof stubFetch>, props: { eid?: string | null; compact?: boolean } = {}) {
  vi.stubGlobal('fetch', fetchMock)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      {/* Default mirrors the Task 11 call style: explicit eid prop. */}
      <EntityDetail oid="oid-1" eid={EID} {...props} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useBrowseStore.setState({
    selectedEid: null,
    viewMode: 'detail',
    revealEid: null,
    ttlFocusEid: null,
    ttlNonce: 0,
  })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('EntityDetail', () => {
  it('renders the overview: labels, parent/child links, properties, backrefs, stats', async () => {
    renderDetail(stubFetch())
    expect(await screen.findByText('pizza:Dog')).toBeTruthy()
    expect(screen.getByText('en: Dog')).toBeTruthy()
    // Parents and children render as navigation links.
    expect(screen.getByText('pizza:Animal')).toBeTruthy()
    expect(screen.getByText('pizza:Corgi')).toBeTruthy()
    // Properties table carries curie + ptype; backrefs carry curie + relation.
    expect(screen.getByText('pizza:hasOwner')).toBeTruthy()
    expect(screen.getByText('ObjectProperty')).toBeTruthy()
    expect(screen.getByText('反向引用')).toBeTruthy()
    expect(screen.getByText('pizza:Kennel')).toBeTruthy()
    expect(screen.getByText('rdfs:domain')).toBeTruthy()
    expect(screen.getByText(/直接子类 2/)).toBeTruthy()
    expect(screen.getByText(/全部后代 7/)).toBeTruthy()
  })

  it('shows comment and deprecated badge when present', async () => {
    renderDetail(stubFetch({ ...entity(), comment: 'Dogs bark.', deprecated: true }))
    expect(await screen.findByText('Dogs bark.')).toBeTruthy()
    expect(screen.getByText('deprecated')).toBeTruthy()
  })

  it('switches to the TTL tab and shows raw turtle', async () => {
    renderDetail(stubFetch())
    await screen.findByText('pizza:Dog')
    await userEvent.click(screen.getByRole('tab', { name: '原始 TTL' }))
    expect(await screen.findByText(/a owl:Class/)).toBeTruthy()
  })

  it('compact mode hides the TTL tab and stats, and fetches no raw TTL', async () => {
    const fetchMock = stubFetch()
    renderDetail(fetchMock, { compact: true })
    expect(await screen.findByText('pizza:Dog')).toBeTruthy()
    expect(screen.getByRole('tab', { name: '概览' })).toBeTruthy()
    expect(screen.queryByRole('tab', { name: '原始 TTL' })).toBeNull()
    expect(screen.queryByText(/直接子类/)).toBeNull()
    expect(screen.getByText('pizza:Animal')).toBeTruthy()
    // Compact renders no TTL tab, so the raw query stays disabled.
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('/raw/'))).toBe(false)
  })

  it('opens on the TTL tab when the inspector TTL signal targets this entity', async () => {
    useBrowseStore.setState({ ttlFocusEid: EID })
    renderDetail(stubFetch())
    // TTL content mounts without any tab click — the signal was consumed.
    expect(await screen.findByText(/a owl:Class/)).toBeTruthy()
  })

  it('falls back to the store selection when eid prop is omitted (old Browse)', async () => {
    useBrowseStore.setState({ selectedEid: EID })
    const fetchMock = stubFetch()
    vi.stubGlobal('fetch', fetchMock)
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <EntityDetail oid="oid-1" />
      </QueryClientProvider>,
    )
    expect(await screen.findByText('pizza:Dog')).toBeTruthy()
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/ontologies/oid-1/entities/${encodeURIComponent(EID)}`,
      expect.anything(),
    )
  })

  it('parent link click selects the parent entity', async () => {
    renderDetail(stubFetch())
    await screen.findByText('pizza:Animal')
    await userEvent.click(screen.getByText('pizza:Animal'))
    expect(useBrowseStore.getState().selectedEid).toBe(PARENT)
  })

  it('backref row click selects the referencing entity', async () => {
    renderDetail(stubFetch())
    expect(await screen.findByText('pizza:Kennel')).toBeTruthy()
    await userEvent.click(screen.getByText('pizza:Kennel'))
    expect(useBrowseStore.getState().selectedEid).toBe('http://example.org/Kennel')
  })
})
