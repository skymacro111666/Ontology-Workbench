import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import InspectorPanel from './InspectorPanel'
import { useBrowseStore } from '../stores/browseStore'
import { useUiStore } from '../stores/uiStore'
import type { Envelope, EntityIR, NodesEdges, SchemaProp } from '../api/types'

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

function stubFetch(
  data: EntityIR = entity(),
  insts: NodesEdges = { nodes: [], edges: [] },
  schema: SchemaProp[] = [],
) {
  return vi.fn(async (url: string | URL) => {
    const u = String(url)
    const body = u.endsWith('/instances') ? insts : u.includes('/assertion-schema') ? schema : data
    return new Response(okEnvelope(body), { headers: { 'Content-Type': 'application/json' } })
  })
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
  useUiStore.setState({ instanceDialog: null, instanceJustCreated: null })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('InspectorPanel', () => {
  it('renders the compact summary: type badge, curie, URI, labels, chips, props, backrefs', async () => {
    renderPanel()
    // Title shows the bare local name; the full curie moves into the hover
    // tooltip (same convention as the chips), the URI block keeps the eid.
    const title = await screen.findByTitle('pizza:Dog')
    expect(title.title).toBe('pizza:Dog')
    expect(screen.queryByText('pizza:Dog')).toBeNull()
    // Type renders as an "OWL CLASS"-style uppercase pill (mockup).
    expect(screen.getByText('CLASS').className).toContain('rounded-full')
    // URI renders as a code block.
    expect(screen.getByText(EID).closest('pre')).toBeTruthy()
    // Label badge: a single label shows the bare value (no lang suffix —
    // the suffix only disambiguates multilingual labels).
    expect(screen.getAllByText('Dog').length).toBe(2) // title + label chip
    expect(screen.getByText('Dogs bark.')).toBeTruthy()
    // Parents/children/backrefs render as chips (label or local name — the
    // full curie moved into the tooltip).
    expect(screen.getByText('Animal').title).toBe('pizza:Animal')
    expect(screen.getByText('Corgi')).toBeTruthy()
    expect(screen.getByText('Kennel')).toBeTruthy()
    // Section titles carry counts (competitor's Subclasses (3) pattern); the
    // property section rides the assertion-schema endpoint and stays absent
    // while that schema is empty.
    expect(screen.getByText('父类 (1)')).toBeTruthy()
    expect(screen.getByText('直接子类 (1)')).toBeTruthy()
    expect(screen.queryByText(/属性 \(/)).toBeNull()
    expect(screen.getByText('被引用 (1)')).toBeTruthy()
  })

  it('suffixes labels with their language only when several coexist', async () => {
    const ent = entity()
    ent.label = { zh: '狗', en: 'Dog' }
    renderPanel(stubFetch(ent))
    expect(await screen.findByText('狗 (zh)')).toBeTruthy()
    expect(screen.getByText('Dog (en)')).toBeTruthy()
  })

  it('groups backrefs by domain/range, dropping the subclass duplicates', async () => {
    const ent = entity()
    ent.referencedBy = [
      // pizza:Kennel — rdfs:domain, far end = the property's range class.
      {
        ...ent.referencedBy[0],
        counterpart: { eid: 'http://example.org/Dept', curie: 'pizza:Dept', label: {}, declared: true },
      },
      {
        eid: 'http://example.org/Leads',
        curie: 'pizza:leads',
        label: { en: 'Leads' },
        relation: 'rdfs:range',
        counterpart: { eid: 'http://www.w3.org/2001/XMLSchema#decimal', curie: 'xsd:decimal', label: {}, declared: false },
      },
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
    const dept = screen.getByText('Dept')
    expect(dept.parentElement?.textContent).toBe('→ Dept')
    // Declared counterparts navigate on click (dotted-underline button);
    // external IRIs (xsd:*) stay plain text.
    expect(screen.getByText('← decimal').tagName).toBe('SPAN')
    await userEvent.click(dept)
    expect(useBrowseStore.getState().selectedEid).toBe('http://example.org/Dept')
  })

  it('lists a class\'s direct instances as navigable chips', async () => {
    const insts: NodesEdges = {
      nodes: [
        { id: 'http://example.org/james', curie: 'hr:james-anderson', label: { en: 'James Anderson' }, kind: 'instance' },
        { id: 'http://example.org/sofia', curie: 'hr:sofia-cruz', label: {}, kind: 'instance' },
      ],
      edges: [],
    }
    const { fetchMock } = renderPanel(stubFetch(entity(), insts))
    // B2: instances are first-class — each row is a chip (label, or the local
    // curie name when labelless) with the full curie in the tooltip.
    const james = await screen.findByRole('button', { name: 'James Anderson' })
    expect(james.title).toBe('hr:james-anderson')
    expect(screen.getByRole('button', { name: 'sofia-cruz' }).title).toBe('hr:sofia-cruz')
    // The panel hit the instances endpoint once, after the class loaded.
    const urls = fetchMock.mock.calls.map(([u]) => String(u))
    expect(urls.filter((u) => u.endsWith('/instances'))).toHaveLength(1)
    // Chip click navigates to the instance's own detail page.
    await userEvent.click(james)
    expect(useBrowseStore.getState().selectedEid).toBe('http://example.org/james')
  })

  it('opens the create-instance dialog from the section header ＋', async () => {
    renderPanel()
    expect(await screen.findByText('实例 (0)')).toBeTruthy()
    await userEvent.click(screen.getByRole('button', { name: '添加实例' }))
    expect(useUiStore.getState().instanceDialog).toEqual({ mode: 'create', parent: EID })
  })

  it('class detail lists usable properties with inherited grouping', async () => {
    // Shapes mirror the backend assertion-schema contract: an object prop
    // points at a declared range class, a datatype prop at an xsd curie.
    const schema: SchemaProp[] = [
      {
        eid: 'http://example.org/wrote',
        curie: 'lib:wrote',
        label: {},
        ptype: 'ObjectProperty',
        inherited: false,
        via: null,
        target: { kind: 'class', curie: 'lib:Book', eid: 'http://example.org/Book', declared: true },
      },
      {
        eid: 'http://example.org/title',
        curie: 'lib:title',
        label: {},
        ptype: 'DatatypeProperty',
        inherited: true,
        via: 'lib:Book',
        target: { kind: 'datatype', curie: 'xsd:string', eid: null, declared: null },
      },
    ]
    const { fetchMock } = renderPanel(stubFetch(entity(), { nodes: [], edges: [] }, schema))
    // Section appears only when the schema is non-empty; counts carry both rows.
    expect(await screen.findByText('属性 (2)')).toBeTruthy()
    // Property names render as bare local names; the range class is a
    // navigable chip with the full curie in its tooltip.
    const book = screen.getByText('Book')
    expect(book.title).toBe('lib:Book')
    expect(screen.getByText('wrote')).toBeTruthy()
    // Inherited rows dim and carry the 「继承自 via」 suffix; datatype
    // targets read as `= localName(xsd curie)`.
    expect(screen.getByText('继承自', { exact: false }).textContent).toContain('lib:Book')
    expect(screen.getByText('= string').tagName).toBe('SPAN')
    // The schema endpoint was queried with this class's eid.
    const urls = fetchMock.mock.calls.map(([u]) => String(u))
    expect(urls.some((u) => u.includes('/assertion-schema?classes='))).toBe(true)
    // Range-class chip click navigates to that class.
    await userEvent.click(book)
    expect(useBrowseStore.getState().selectedEid).toBe('http://example.org/Book')
  })

  it('shows 无 for a class without instances', async () => {
    renderPanel()
    expect(await screen.findByText('无')).toBeTruthy()
    expect(screen.getByText('实例 (0)')).toBeTruthy()
  })

  it('skips the instances section and fetch for non-class entities', async () => {
    const prop = { ...entity(), type: 'ObjectProperty' as const }
    const { fetchMock } = renderPanel(stubFetch(prop))
    expect(await screen.findByTitle('pizza:Dog')).toBeTruthy()
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

  it('maps the query failure by envelope code (T8①)', async () => {
    renderPanel(stubFetchError())
    // NOT_FOUND maps to localized copy instead of the old blanket sentence.
    expect(await screen.findByText('未找到请求的资源')).toBeTruthy()
  })
})
