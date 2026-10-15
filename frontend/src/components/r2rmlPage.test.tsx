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
  it('renders the structure tab with cards, pills and skipped badge', async () => {
    /** 结构页签默认打开:一表一卡(表名+类 pill+统计),datatype 小 pill、FK ⇄ 行、skipped 徽章都在。 */
    vi.stubGlobal('fetch', vi.fn(async () => ok(DOC)))
    page()
    expect(await screen.findByText('customer')).toBeTruthy() // 卡头表名
    expect(screen.getByText('Customer')).toBeTruthy() // 类名 pill
    expect(screen.getByText('1 列 · 1 关系')).toBeTruthy() // 统计徽章
    expect(screen.getByText('xsd:string')).toBeTruthy() // datatype pill
    expect(screen.getByText('⇄')).toBeTruthy() // FK 徽标
    expect(screen.getByText(/customer_id → customer\.id/)).toBeTruthy() // FK 行
    expect(screen.getByText(/audit_log/)).toBeTruthy() // skipped 行(A3 未做,保持原样)
  })

  it('collapses and expands a table card from its head', async () => {
    /** B2:点卡头收起=只剩表名/统计一行;再点展开。 */
    vi.stubGlobal('fetch', vi.fn(async () => ok(DOC)))
    page()
    expect(await screen.findByText('xsd:string')).toBeTruthy()
    const head = screen.getByRole('button', { name: /customer/ })
    expect(head.getAttribute('aria-expanded')).toBe('true')
    await userEvent.click(head)
    expect(head.getAttribute('aria-expanded')).toBe('false')
    expect(screen.queryByText('xsd:string')).toBeNull()
    expect(screen.getByText('1 列 · 1 关系')).toBeTruthy() // 收起仍见统计
    await userEvent.click(head)
    expect(screen.getByText('xsd:string')).toBeTruthy()
  })

  it('switches to the source tab showing the Turtle text', async () => {
    /** 源码页签=CM6 编辑器,内容在 .cm-content(CM6 按行拆节点,取 textContent)。 */
    vi.stubGlobal('fetch', vi.fn(async () => ok(DOC)))
    const { container } = page()
    await screen.findByText('customer')
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
    expect(await screen.findAllByText('customer')).toHaveLength(2) // 两张同名表卡
    expect(screen.getByText('Customer2')).toBeTruthy() // 第二张卡的类 pill 照常渲染
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

describe('R2rmlPage drift check fallback', () => {
  it('falls back to the picker when the saved connection is gone (404)', async () => {
    /** 行上档案连接已被删:直连 POST 404 → 弹挑连接框(spec 决策2「档已删」分支). */
    const driftOk = (findings: unknown[]) =>
      ok({ drifted: findings.length > 0, checkedAt: '2026-10-14T10:30:00Z', findings })
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (String(url).includes('/r2rml/drift')) {
          if ((init?.method ?? 'GET') === 'POST') return notFound()
          return driftOk([])
        }
        if (String(url).includes('/db-connections'))
          return ok([{ id: 'c2', name: 'shop', dbType: 'sqlite' }])
        return ok({ ...DOC })
      }),
    )
    page()
    await userEvent.click(await screen.findByRole('button', { name: '检查漂移' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByLabelText(/数据库连接/)).toBeTruthy()
  })
})
