import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import R2rmlPage from './R2rmlPage'

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
  contentHash: 'c'.repeat(64),
  previousExists: false,
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

function page() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <R2rmlPage oid="oid-1" />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('R2rmlPage', () => {
  it('renders the structure tab with correspondences and skipped badge', async () => {
    /** 结构页签默认打开:表→类行、列→属性行、skipped 徽章都在。 */
    vi.stubGlobal('fetch', vi.fn(async () => ok(DOC)))
    page()
    expect(await screen.findByText('customer → Customer')).toBeTruthy()
    expect(screen.getByText('name → name (xsd:string)')).toBeTruthy()
    expect(screen.getByText(/hasCustomer: customer_id → customer.id/)).toBeTruthy()
    expect(screen.getByText(/audit_log/)).toBeTruthy() // skipped 徽章
  })

  it('switches to the source tab showing the Turtle text', async () => {
    /** 源码页签=CM6 编辑器,内容在 .cm-content(CM6 按行拆节点,取 textContent)。 */
    vi.stubGlobal('fetch', vi.fn(async () => ok(DOC)))
    const { container } = page()
    await screen.findByText('customer → Customer')
    await userEvent.click(screen.getByRole('radio', { name: '源码' }))
    await waitFor(() => {
      const content = container.querySelector('.cm-content') as HTMLElement
      expect(content?.textContent).toContain('@prefix rr:')
    })
  })

  it('shows the guide copy when the ontology has no mapping', async () => {
    /** 无映射:页面空态=指路文案(不从 toast 改)。 */
    vi.stubGlobal('fetch', notFound)
    page()
    expect(await screen.findByText(/来自数据库起草的本体才有/)).toBeTruthy()
  })
})

describe('R2rmlPage key hygiene', () => {
  it('renders duplicate table names without React key collisions', async () => {
    /** 手打两 map 共用同名表(P2 终审 minor):结构列表不得触发 React 同 key 告警. */
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const dup = {
      ...DOC,
      structure: [
        ...DOC.structure,
        {
          table: 'customer',
          className: 'Customer2',
          subjectTemplate: 'https://local/shop/customer2/{id}',
          columnProps: [],
          fkProps: [],
        },
      ],
    }
    vi.stubGlobal('fetch', vi.fn(async () => ok(dup)))
    page()
    await screen.findAllByText(/customer → Customer/)
    expect(
      errSpy.mock.calls.some((c) => String(c[0]).includes('same key')),
    ).toBe(false)
    errSpy.mockRestore()
  })
})
