import { cleanup, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import R2rmlDialog from './R2rmlDialog'
import { useUiStore } from '../stores/uiStore'

const ok = (data: unknown) =>
  new Response(JSON.stringify({ code: 'OK', message: 'ok', data, hint: null, request_id: 'r' }), {
    headers: { 'Content-Type': 'application/json' },
  })
const notFound = () =>
  new Response(
    JSON.stringify({
      code: 'NOT_FOUND', message: 'No R2RML mapping', data: null, hint: null, request_id: 'r',
    }),
    { status: 404, headers: { 'Content-Type': 'application/json' } },
  )

const DOC = {
  filename: 'shop.r2rml.ttl',
  baseRevision: 0,
  schemaHash: 'h',
  createdAt: '2026-10-12T00:00:00Z',
  skippedTables: ['audit_log'],
  content: '@prefix rr: <http://www.w3.org/ns/r2rml#> .',
  structure: [
    {
      table: 'customer',
      className: 'Customer',
      subjectTemplate: 'https://local/shop/customer/{id}',
      columnProps: [{ predicate: 'name', column: 'name', datatype: 'xsd:string' }],
      fkProps: [
        { predicate: 'hasCustomer', childColumn: 'customer_id',
          parentTable: 'customer', parentColumn: 'id' },
      ],
    },
  ],
}

function renderDialog() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <R2rmlDialog oid="oid-1" />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  useUiStore.getState().setR2rmlOpen(false)
})

describe('R2rmlDialog', () => {
  it('renders the structured correspondences, skipped badge and read-only turtle', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ok(DOC)))
    useUiStore.getState().setR2rmlOpen(true)
    renderDialog()

    expect(await screen.findByText('R2RML 映射')).toBeTruthy()
    // Title renders with the dialog; rows only after fetch resolves, so the
    // first data assertion must wait too (the rest ride the same render).
    expect(await screen.findByText('customer → Customer')).toBeTruthy()
    expect(screen.getByText('name → name (xsd:string)')).toBeTruthy()
    expect(screen.getByText(/audit_log/)).toBeTruthy() // skipped 徽章
    expect(screen.getByText(/rr:/)).toBeTruthy() // Turtle 源码
  })

  it('shows the guide copy on 404 (ontology without a mapping)', async () => {
    vi.stubGlobal('fetch', notFound)
    useUiStore.getState().setR2rmlOpen(true)
    renderDialog()
    expect(await screen.findByText(/来自数据库起草的本体才有/)).toBeTruthy()
  })
})
