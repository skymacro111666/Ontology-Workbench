import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
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
  dbConnectionId: 'conn-1',
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

describe('R2rmlPage drift check', () => {
  const driftOk = (findings: unknown[]) =>
    ok({
      drifted: findings.length > 0,
      checkedAt: '2026-10-14T10:30:00Z',
      findings,
    })

  function stubFetch(doc: object, drift: Response, conns: unknown[] = []) {
    const calls: string[] = []
    const bodies: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push(`${init?.method ?? 'GET'} ${url}`)
        if (String(url).includes('/r2rml/drift')) {
          bodies.push(String(init?.body ?? ''))
          return drift
        }
        if (String(url).includes('/db-connections')) return ok(conns)
        return ok(doc)
      }),
    )
    return { calls, bodies }
  }

  it('posts drift directly when the row has a connection; clean banner shows', async () => {
    /** 行上有档案连接:点击直接 POST,绿横幅「无漂移 (时间)」. */
    const { calls, bodies } = stubFetch({ ...DOC }, driftOk([]))
    page()
    await userEvent.click(await screen.findByRole('button', { name: '检查漂移' }))
    await waitFor(() => expect(screen.getByText(/无漂移/)).toBeTruthy())
    expect(calls).toContainEqual('POST /api/v1/ontologies/oid-1/r2rml/drift')
    expect(bodies[0]).toBe('{}')
  })

  it('opens the connection picker when the row has none', async () => {
    /** 行上无档案:点击弹挑连接框,选中后带 connectionId POST. */
    const { bodies } = stubFetch(
      { ...DOC, dbConnectionId: null },
      driftOk([]),
      [{ id: 'c2', name: 'shop', dbType: 'sqlite' }],
    )
    page()
    await userEvent.click(await screen.findByRole('button', { name: '检查漂移' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.selectOptions(within(dialog).getByLabelText(/数据库连接/), 'c2')
    await userEvent.click(within(dialog).getByRole('button', { name: '检查漂移' }))
    await waitFor(() => expect(screen.getByText(/无漂移/)).toBeTruthy())
    expect(bodies[0]).toContain('"connectionId":"c2"')
  })

  it('renders each drift finding in the amber banner', async () => {
    /** 漂移:琥珀横幅逐条渲染 detail. */
    stubFetch(
      { ...DOC },
      driftOk([{ table: 'customer', kind: 'column_missing', detail: '列 customer.name 已删除' }]),
    )
    page()
    await userEvent.click(await screen.findByRole('button', { name: '检查漂移' }))
    await waitFor(() => expect(screen.getByText(/发现漂移/)).toBeTruthy())
    expect(screen.getByText(/列 customer\.name 已删除/)).toBeTruthy()
  })
})
