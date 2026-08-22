import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import InspectorPanel from './InspectorPanel'
import { useBrowseStore } from '../stores/browseStore'
import type { Envelope, EntityIR } from '../api/types'

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

function stubFetch(data: EntityIR = entity()) {
  return vi.fn(async () =>
    new Response(okEnvelope(data), { headers: { 'Content-Type': 'application/json' } }),
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
  useBrowseStore.setState({ selectedEid: null, viewMode: 'detail', revealEid: null })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('InspectorPanel', () => {
  it('renders the compact summary: type badge, curie, URI, labels, chips, props, backrefs', async () => {
    renderPanel()
    expect(await screen.findByText('pizza:Dog')).toBeTruthy()
    // Type badge is an "OWL CLASS"-style microlabel badge (uppercase via CSS).
    expect(screen.getByText('Class').className).toContain('microlabel')
    // URI renders as a code block.
    expect(screen.getByText(EID).closest('pre')).toBeTruthy()
    expect(screen.getByText('en: Dog')).toBeTruthy()
    expect(screen.getByText('Dogs bark.')).toBeTruthy()
    // Parents/children/backrefs render as chips; props mini table carries curie + ptype.
    expect(screen.getByText('pizza:Animal')).toBeTruthy()
    expect(screen.getByText('pizza:Corgi')).toBeTruthy()
    expect(screen.getByText('pizza:hasOwner')).toBeTruthy()
    expect(screen.getByText('ObjectProperty')).toBeTruthy()
    expect(screen.getByText('pizza:Kennel')).toBeTruthy()
  })

  it('truncates long comments to two lines', async () => {
    const long = 'A dog is a domesticated descendant of the wolf and much more text follows here to overflow the two-line clamp.'
    renderPanel(stubFetch({ ...entity(), comment: long }))
    const p = await screen.findByText(long)
    expect(p.className).toContain('line-clamp-2')
  })

  it('chip click selects that entity (parent and backref)', async () => {
    renderPanel()
    await screen.findByText('pizza:Animal')
    await userEvent.click(screen.getByText('pizza:Animal'))
    expect(useBrowseStore.getState().selectedEid).toBe(PARENT)
    await userEvent.click(screen.getByText('pizza:Kennel'))
    expect(useBrowseStore.getState().selectedEid).toBe('http://example.org/Kennel')
  })

  it('raw TTL action switches the view mode to detail', async () => {
    useBrowseStore.setState({ viewMode: 'graph' })
    renderPanel()
    await screen.findByText('pizza:Dog')
    await userEvent.click(screen.getByRole('button', { name: '原始 TTL' }))
    expect(useBrowseStore.getState().viewMode).toBe('detail')
  })

  it('overview action links to the graph page with the focus param', async () => {
    renderPanel()
    await screen.findByText('pizza:Dog')
    const link = screen.getByRole('link', { name: '在总览中查看' })
    expect(link.getAttribute('href')).toBe(`/graph/oid-1?focus=${encodeURIComponent(EID)}`)
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
