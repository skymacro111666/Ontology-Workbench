import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import InspectorPanel from './InspectorPanel'
import { useBrowseStore } from '../stores/browseStore'
import type { Envelope, EntityIR, NodesEdges } from '../api/types'

const EID = 'http://example.org/Dog'
const PARENT = 'http://example.org/Animal'

/** Same entity() shape as entityDetail.test.tsx; comment set so the
 *  truncation test can use its own long text. */
function entity(): EntityIR {
  return {
    eid: EID,
    curie: 'pizza:Dog',
    type: 'Class',
    label: { en: 'Dog' },
    comment: 'Dogs bark.',
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

function okEnvelope(data: unknown) {
  return JSON.stringify({
    code: 'OK',
    message: 'ok',
    data,
    hint: null,
    request_id: 'r',
  } satisfies Envelope<unknown>)
}

function stubFetch(data: EntityIR = entity(), insts: NodesEdges = { nodes: [], edges: [] }) {
  return vi.fn(async (url: string | URL) =>
    new Response(
      okEnvelope(String(url).endsWith('/instances') ? insts : data),
      { headers: { 'Content-Type': 'application/json' } },
    ),
  )
}

/** External entity: envelope carries a non-OK code so unwrap throws. */
function stubFetchError() {
  return vi.fn(async () =>
    new Response(
      JSON.stringify({ code: 'NOT_FOUND', message: 'nope', data: null, hint: null, request_id: 'r' } satisfies Envelope<null>),
      { headers: { 'Content-Type': 'application/json' } },
    ),
  )
}

function renderPanel(
  fetchMock: ReturnType<typeof stubFetch> = stubFetch(),
  props: { eid?: string | null } = {},
) {
  vi.stubGlobal('fetch', fetchMock)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return {
    fetchMock,
    ...render(
      <QueryClientProvider client={qc}>
        {/* Link needs a router context; the T11 assembly sits inside the app router. */}
        <MemoryRouter>
          <InspectorPanel oid="oid-1" eid={EID} {...props} />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  }
}

beforeEach(() => {
  useBrowseStore.setState({ selectedEid: null, revealEid: null })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('InspectorPanel', () => {
  it('renders the compact summary: type badge, curie, URI, labels, chips, props, backrefs', async () => {
    renderPanel()
    expect(await screen.findByText('pizza:Dog')).toBeTruthy()
    // Type renders as an "OWL CLASS"-style uppercase pill (mockup).
    expect(screen.getByText('CLASS').className).toContain('rounded-full')
    // URI renders as a code block.
    expect(screen.getByText(EID).closest('pre')).toBeTruthy()
    // Label badge: "value lang" pill (mockup §7.2).
    expect(screen.getByText('Dog en')).toBeTruthy()
    expect(screen.getByText('Dogs bark.')).toBeTruthy()
    // Parents/children/backrefs render as chips (label or local name — the
    // full curie moved into the tooltip).
    expect(screen.getByText('Animal').title).toBe('pizza:Animal')
    expect(screen.getByText('Corgi')).toBeTruthy()
    expect(screen.getByText('Kennel')).toBeTruthy()
    // Section titles carry counts (competitor's Subclasses (3) pattern); the
    // props mini table is gone — 被引用's domain rows carry the same properties.
    expect(screen.getByText('父类 (1)')).toBeTruthy()
    expect(screen.getByText('直接子类 (1)')).toBeTruthy()
    expect(screen.queryByText(/属性 \(/)).toBeNull()
    expect(screen.getByText('被引用 (1)')).toBeTruthy()
  })

  it('groups backrefs by domain/range, dropping the subclass duplicates', async () => {
    const ent = entity()
    ent.referencedBy = [
      // pizza:Kennel — rdfs:domain, far end = the property's range class.
      {
        ...ent.referencedBy[0],
        counterpart: { eid: 'http://example.org/Dept', curie: 'pizza:Dept', label: {} },
      },
      { eid: 'http://example.org/Leads', curie: 'pizza:leads', label: { en: 'Leads' }, relation: 'rdfs:range' },
      { eid: 'http://example.org/Puppy', curie: 'pizza:Puppy', label: {}, relation: 'subClassOf' },
    ]
    renderPanel(stubFetch(ent))
    expect(await screen.findByText('作为定义域 (1)')).toBeTruthy()
    expect(screen.getByText('作为值域 (1)')).toBeTruthy()
    // subClassOf backrefs duplicate 直接子类 — they drop out of 被引用.
    expect(screen.queryByText('Puppy')).toBeNull()
    expect(screen.getByText('被引用 (2)')).toBeTruthy()
    // Labeled refs show the human name; the curie rides in the tooltip.
    expect(screen.getByText('Leads').title).toBe('pizza:leads')
    // Domain rows pair the ref with the axiom's far end (→ range class);
    // untyped refs show no arrow.
    expect(screen.getByText('→ Dept')).toBeTruthy()
  })

  it('lists a class\'s direct instances below the backrefs (label + curie rows)', async () => {
    const insts: NodesEdges = {
      nodes: [
        { id: 'http://example.org/james', curie: 'hr:james-anderson', label: { en: 'James Anderson' }, kind: 'instance' },
        { id: 'http://example.org/sofia', curie: 'hr:sofia-cruz', label: {}, kind: 'instance' },
      ],
      edges: [],
    }
    const { fetchMock } = renderPanel(stubFetch(entity(), insts))
    expect(await screen.findByText('James Anderson')).toBeTruthy()
    // Labeled instance shows both label and mono curie; labelless falls back to curie only.
    expect(screen.getByText('hr:james-anderson')).toBeTruthy()
    expect(screen.getByText('hr:sofia-cruz')).toBeTruthy()
    // The panel hit the instances endpoint once, after the class loaded.
    const urls = fetchMock.mock.calls.map(([u]) => String(u))
    expect(urls.filter((u) => u.endsWith('/instances'))).toHaveLength(1)
  })

  it('shows 无 for a class without instances', async () => {
    renderPanel()
    expect(await screen.findByText('无')).toBeTruthy()
    expect(screen.getByText('实例 (0)')).toBeTruthy()
  })

  it('skips the instances section and fetch for non-class entities', async () => {
    const prop = { ...entity(), type: 'ObjectProperty' as const }
    const { fetchMock } = renderPanel(stubFetch(prop))
    expect(await screen.findByText('pizza:Dog')).toBeTruthy()
    expect(screen.queryByText(/^实例/)).toBeNull()
    expect(fetchMock.mock.calls.map(([u]) => String(u)).some((u) => u.endsWith('/instances'))).toBe(
      false,
    )
  })

  it('truncates long comments to two lines', async () => {
    const long = 'A dog is a domesticated descendant of the wolf and much more text follows here to overflow the two-line clamp.'
    renderPanel(stubFetch({ ...entity(), comment: long }))
    const p = await screen.findByText(long)
    expect(p.className).toContain('line-clamp-2')
  })

  it('chip click selects that entity (parent and backref)', async () => {
    renderPanel()
    await screen.findByText('Animal')
    await userEvent.click(screen.getByText('Animal'))
    expect(useBrowseStore.getState().selectedEid).toBe(PARENT)
    await userEvent.click(screen.getByText('Kennel'))
    expect(useBrowseStore.getState().selectedEid).toBe('http://example.org/Kennel')
  })

  it('shows the empty state and fetches nothing when no entity is selected', () => {
    const { fetchMock } = renderPanel(stubFetch(), { eid: null })
    expect(screen.getByText('在树或图中选择一个实体')).toBeTruthy()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('shows the external-entity note when the query fails', async () => {
    renderPanel(stubFetchError())
    expect(await screen.findByText('外部实体（未在本体中声明），无详情页')).toBeTruthy()
  })
})
