import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { MemoryRouter, useLocation } from 'react-router'
import { api } from '../api/client'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import DraftFromDbDialog from './DraftFromDbDialog'
import { useUiStore } from '../stores/uiStore'
import type { Envelope } from '../api/types'

/** Envelope helpers matching the API contract (code/message/data/hint/request_id). */
const ok = (data: unknown) =>
  new Response(JSON.stringify({ code: 'OK', message: 'ok', data, hint: null, request_id: 'r' }), {
    headers: { 'Content-Type': 'application/json' },
  })

const err = (code: string) =>
  new Response(
    JSON.stringify({ code, message: 'boom', data: null, hint: null, request_id: 'r' } satisfies Envelope<null>),
    { headers: { 'Content-Type': 'application/json' } },
  )

const ENGINES = [
  { dbType: 'sqlite', label: 'SQLite', installed: true },
  { dbType: 'postgres', label: 'PostgreSQL', installed: false },
  { dbType: 'mysql', label: 'MySQL', installed: false },
]

const SCHEMA = {
  databaseName: 'x',
  tables: [{ name: 'customer', comment: null, columns: [], foreignKeys: [] }],
}

/** POSTs to the reflect endpoint, decoded from the JSON body. */
function schemaBodies(fetchMock: Mock) {
  return fetchMock.mock.calls
    .filter(([url, init]) => String(url).includes('/drafting/schema') && init?.method === 'POST')
    .map(([, init]) => JSON.parse(String(init.body)))
}

function renderDialog() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <DraftFromDbDialog />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useUiStore.getState().setDraftOpen(true)
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  useUiStore.getState().setDraftOpen(false)
})

describe('DraftFromDbDialog — step 1 连接', () => {  it('renders the dialog from the store flag with engines fetched', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).includes('/db-connections/engines')) return ok(ENGINES)
      return ok([])
    })
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()
    expect(await screen.findByText('从数据库起草')).toBeTruthy()
    // engines list arrived: uninstalled dialects render disabled
    const select = await screen.findByLabelText('数据库类型')
    const options = [...select.querySelectorAll('option')]
    expect(options.map((o) => o.value)).toContain('sqlite')
    const pg = options.find((o) => o.value === 'postgres')
    expect(pg?.disabled).toBe(true)
  })

  it('POSTs sqlite raw values and advances to the tables step', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).includes('/db-connections/engines')) return ok(ENGINES)
      if (String(url).includes('/db-connections')) return ok([])
      if (String(url).includes('/drafting/schema')) return ok({ schema: SCHEMA, tableCount: 1 })
      return ok(null)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()

    await screen.findByLabelText('路径')
    await userEvent.type(screen.getByLabelText('路径'), '/tmp/x.db')
    await userEvent.click(screen.getByRole('button', { name: '读取表结构' }))

    await waitFor(() => expect(schemaBodies(fetchMock)).toHaveLength(1))
    expect(schemaBodies(fetchMock)[0]).toEqual({ dbType: 'sqlite', database: '/tmp/x.db' })
    // advancing: the step-2 heading replaces the connection form
    expect(await screen.findByText('选表与选项')).toBeTruthy()
    expect(screen.queryByLabelText('路径')).toBeNull()
  })

  it('keeps step 1 and shows the mapped error on DB_CONNECT_FAILED', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).includes('/db-connections/engines')) return ok(ENGINES)
      if (String(url).includes('/db-connections')) return ok([])
      if (String(url).includes('/drafting/schema')) return err('DB_CONNECT_FAILED')
      return ok(null)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()

    await screen.findByLabelText('路径')
    await userEvent.type(screen.getByLabelText('路径'), '/tmp/nope.db')
    await userEvent.click(screen.getByRole('button', { name: '读取表结构' }))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('数据库连接失败')
    // still on step 1: the connection form is intact for a retry
    expect(screen.getByLabelText('路径')).toBeTruthy()
    expect(screen.getByRole('button', { name: '读取表结构' })).toBeTruthy()
  })
})

const SCHEMA2 = {
  databaseName: 'shop',
  tables: [
    {
      name: 'customer',
      comment: '客户',
      columns: [
        { name: 'id', type: 'INTEGER', nullable: false, primaryKey: true, unique: false, comment: null },
        { name: 'name', type: 'VARCHAR(80)', nullable: true, primaryKey: false, unique: false, comment: null },
      ],
      foreignKeys: [],
    },
    {
      name: 'orders',
      comment: '订单',
      columns: [{ name: 'id', type: 'INTEGER', nullable: false, primaryKey: true, unique: false, comment: null }],
      foreignKeys: [{ column: 'customer_id', refTable: 'customer', refColumn: 'id' }],
    },
  ],
}

/** Router carrying the dialog to step 2: engines + reflect + (optional) AI status. */
function step2Router(opts: { configured?: boolean } = {}) {
  let polls = 0
  const calls: { generate: unknown[]; jobs: string[] } = { generate: [], jobs: [] }
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url)
    if (u.includes('/db-connections/engines')) return ok(ENGINES)
    if (u.includes('/db-connections')) return ok([])
    if (u.includes('/ai/status')) return ok({ configured: opts.configured ?? true, provider: 'openai', model: 'm', source: 'env' })
    if (u.includes('/drafting/schema')) return ok({ schema: SCHEMA2, tableCount: 2 })
    if (u.includes('/drafting/generate')) {
      calls.generate.push(JSON.parse(String(init?.body)))
      return ok({ jobId: 'job-1' })
    }
    if (u.includes('/drafting/jobs/')) {
      calls.jobs.push(u)
      polls += 1
      if (polls === 1) return ok({ status: 'running', batch: 1, batchCount: 2 })
      return ok({
        status: 'done',
        batch: 2,
        batchCount: 2,
        result: { decisions: { classes: [], objectProperties: [], dataProperties: [] }, ttl: '', lintFindings: [], stats: {} },
      })
    }
    return ok(null)
  })
  return { fetchMock, calls }
}

/** Drive the dialog to step 2 (reflect done) and hand back the screen. */
async function atStep2() {
  renderDialog()
  await screen.findByLabelText('路径')
  await userEvent.type(screen.getByLabelText('路径'), '/tmp/shop.db')
  await userEvent.click(screen.getByRole('button', { name: '读取表结构' }))
  await screen.findByText('customer')
}

describe('DraftFromDbDialog — step 2 选表与生成', () => {
  it('renders the table list with comments, counts, search and 已选 counter', async () => {
    const { fetchMock } = step2Router()
    vi.stubGlobal('fetch', fetchMock)
    await atStep2()

    expect(screen.getByText('客户')).toBeTruthy()
    expect(screen.getByText('订单')).toBeTruthy()
    expect(screen.getByText('2 列')).toBeTruthy()
    expect(screen.getByText('FK ×1')).toBeTruthy()
    expect(screen.getByText('已选 2/500')).toBeTruthy()

    // search narrows the list; the hidden row leaves the tree
    await userEvent.type(screen.getByLabelText('搜索表名 / 注释…'), 'cust')
    expect(screen.getByText('customer')).toBeTruthy()
    expect(screen.queryByText('订单')).toBeNull()

    // 全选 re-checks everything visible
    await userEvent.click(screen.getByRole('button', { name: '全选' }))
    expect(screen.getByText('已选 2/500')).toBeTruthy()
  })

  it('namespace defaults from the database name and is editable', async () => {
    const { fetchMock } = step2Router()
    vi.stubGlobal('fetch', fetchMock)
    await atStep2()

    const ns = screen.getByLabelText('命名空间') as HTMLInputElement
    expect(ns.value).toBe('https://local/shop#')
    await userEvent.clear(ns)
    await userEvent.type(ns, 'https://ex.org/x#')
    expect(ns.value).toBe('https://ex.org/x#')
  })

  it('disables 生成草稿 without AI and 去配置 opens the AI settings dialog', async () => {
    const { fetchMock } = step2Router({ configured: false })
    vi.stubGlobal('fetch', fetchMock)
    await atStep2()

    const btn = screen.getByRole('button', { name: '生成草稿' }) as HTMLButtonElement
    expect(btn.disabled).toBe(true)
    expect(screen.getByText('AI 未配置——生成草稿需要先配置模型')).toBeTruthy()

    useUiStore.getState().setAiSettingsOpen(false)
    await userEvent.click(screen.getByRole('button', { name: '去配置' }))
    expect(useUiStore.getState().aiSettingsOpen).toBe(true)
  })

  it('generates with the selected subset and polls the job to done', async () => {
    const { fetchMock, calls } = step2Router()
    vi.stubGlobal('fetch', fetchMock)
    await atStep2()

    // deselect orders: the generate body must carry only customer
    const rows = screen.getAllByRole('checkbox')
    await userEvent.click(rows[rows.length - 1])
    expect(screen.getByText('已选 1/500')).toBeTruthy()

    await userEvent.click(screen.getByRole('button', { name: '生成草稿' }))

    // mid-poll: the first running response shows the batch line
    expect(await screen.findByText('正在生成草稿… 第 1/2 批')).toBeTruthy()

    // then the done poll advances to step 3 (preview pane stub)
    expect(await screen.findByText('预览与导入', { selector: '[data-step-name]' })).toBeTruthy()

    expect(calls.generate).toHaveLength(1)
    expect(calls.generate[0]).toEqual({
      schema: { databaseName: 'shop', tables: [SCHEMA2.tables[0]] },
      namespace: 'https://local/shop#',
      labelLanguage: 'zh',
    })
  })
})

const RESULT = {
  decisions: {
    classes: [
      { name: 'Customer', label: '客户', comment: null, sourceTable: 'customer', parentName: null },
      { name: 'Order', label: '订单', comment: null, sourceTable: 'orders', parentName: null },
    ],
    objectProperties: [
      { name: 'hasCustomer', label: null, domain: 'Order', range: 'Customer', sourceFk: 'orders.customer_id' },
    ],
    dataProperties: [
      { name: 'name', label: null, domain: 'Customer', datatype: 'xsd:string', sourceColumn: 'customer.name' },
    ],
  },
  ttl: 'shop:Customer a owl:Class .',
  lintFindings: [
    {
      ruleId: 'missing-label',
      name: null,
      severity: 'warning',
      durationMs: 0,
      findings: [{ ruleId: 'missing-label', severity: 'warning', subject: 'Order', subjectCurie: 'shop:Order', params: {} }],
      total: 1,
      truncated: false,
      error: null,
    },
  ],
  stats: { classCount: 2, objectPropertyCount: 1, dataPropertyCount: 1, elapsedMs: 900, inTokens: 10, outTokens: 5, batchCount: 1 },
}

/** Router carrying the dialog through generate to step 3. */
function step3Router() {
  const imports: unknown[] = []
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url)
    if (u.includes('/db-connections/engines')) return ok(ENGINES)
    if (u.includes('/db-connections')) return ok([])
    if (u.includes('/ai/status')) return ok({ configured: true, provider: 'openai', model: 'm', source: 'env' })
    if (u.includes('/drafting/schema')) return ok({ schema: SCHEMA2, tableCount: 2 })
    if (u.includes('/drafting/generate')) return ok({ jobId: 'job-9' })
    if (u.includes('/drafting/jobs/')) return ok({ status: 'done', batch: 1, batchCount: 1, result: RESULT })
    if (u.includes('/drafting/import') && init?.method === 'POST') {
      imports.push(JSON.parse(String(init.body)))
      return ok({ ontologyId: 'oid-9', title: 'shop', lintFindings: [] })
    }
    if (u === '/api/v1/ontologies') return ok({ items: [], total: 0 })
    return ok(null)
  })
  return { fetchMock, imports }
}

/** Location + ontologies-list probes so navigation and invalidation show. */
function LocationProbe() {
  const loc = useLocation()
  return <span data-testid="loc">{loc.pathname}</span>
}

function renderWizard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const OntologiesProbe = () => {
    useQuery({ queryKey: ['ontologies'], queryFn: () => api.get('/api/v1/ontologies') })
    return null
  }
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/']}>
        <LocationProbe />
        <OntologiesProbe />
        <DraftFromDbDialog />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function atStep3() {
  renderWizard()
  await screen.findByLabelText('路径')
  await userEvent.type(screen.getByLabelText('路径'), '/tmp/shop.db')
  await userEvent.click(screen.getByRole('button', { name: '读取表结构' }))
  await screen.findByText('customer')
  await userEvent.click(screen.getByRole('button', { name: '生成草稿' }))
  await screen.findByText('hasCustomer')
}

describe('DraftFromDbDialog — step 3 预览与导入', () => {
  it('renders decision groups, lint findings and the TTL preview', async () => {
    const { fetchMock } = step3Router()
    vi.stubGlobal('fetch', fetchMock)
    await atStep3()

    expect(screen.getByText('Customer')).toBeTruthy()
    expect(screen.getByText('订单')).toBeTruthy()
    expect(screen.getByText('hasCustomer')).toBeTruthy()
    expect(screen.getByText('Order → Customer')).toBeTruthy()
    expect(screen.getByText('missing-label')).toBeTruthy()
    expect(screen.getByText('shop:Customer a owl:Class .')).toBeTruthy()
    // stats tiles
    expect(screen.getByText('2')).toBeTruthy()
  })

  it('imports the kept subset with rejectedClassNames and jumps to the ontology', async () => {
    const { fetchMock, imports } = step3Router()
    vi.stubGlobal('fetch', fetchMock)
    await atStep3()

    // reject Customer: its row leaves the kept set
    await userEvent.click(screen.getByLabelText('Customer'))

    await userEvent.click(screen.getByRole('button', { name: '导入' }))

    // navigation + last-oid + dialog closed
    await waitFor(() => expect(screen.getByTestId('loc').textContent).toBe('/browse/oid-9'))
    expect(localStorage.getItem('ow_last')).toBe('oid-9')
    await waitFor(() => expect(useUiStore.getState().draftOpen).toBe(false))

    expect(imports).toHaveLength(1)
    expect(imports[0]).toEqual({
      schema: SCHEMA2,
      decisions: {
        classes: [RESULT.decisions.classes[1]],
        objectProperties: RESULT.decisions.objectProperties,
        dataProperties: RESULT.decisions.dataProperties,
      },
      rejectedClassNames: ['Customer'],
      namespace: 'https://local/shop#',
      filename: 'shop-draft.ttl',
      labelLanguage: 'zh',
    })
  })

  it('drops unchecked object/data properties from the import body', async () => {
    const { fetchMock, imports } = step3Router()
    vi.stubGlobal('fetch', fetchMock)
    await atStep3()

    await userEvent.click(screen.getByLabelText('hasCustomer'))
    await userEvent.click(screen.getByLabelText('Customer.name'))

    await userEvent.click(screen.getByRole('button', { name: '导入' }))
    await waitFor(() => expect(imports).toHaveLength(1))

    expect(imports[0]).toMatchObject({
      decisions: { objectProperties: [], dataProperties: [] },
      rejectedClassNames: [],
    })
  })

  it('imports under an edited filename (duplicate-409 recovery)', async () => {
    const { fetchMock, imports } = step3Router()
    vi.stubGlobal('fetch', fetchMock)
    await atStep3()

    const file = screen.getByLabelText('文件名') as HTMLInputElement
    expect(file.value).toBe('shop-draft.ttl')
    await userEvent.clear(file)
    await userEvent.type(file, 'shop-draft-v2.ttl')

    await userEvent.click(screen.getByRole('button', { name: '导入' }))
    await waitFor(() => expect(imports).toHaveLength(1))
    expect(imports[0]).toMatchObject({ filename: 'shop-draft-v2.ttl' })
  })

  it('abandons the poll loop when the dialog closes and reopens mid-generate', async () => {
    let release = false
    const jobPolls: string[] = []
    const fetchMock = vi.fn(async (url: string) => {
      const u = String(url)
      if (u.includes('/db-connections/engines')) return ok(ENGINES)
      if (u.includes('/db-connections')) return ok([])
      if (u.includes('/ai/status')) return ok({ configured: true, provider: 'openai', model: 'm', source: 'env' })
      if (u.includes('/drafting/schema')) return ok({ schema: SCHEMA2, tableCount: 2 })
      if (u.includes('/drafting/generate')) return ok({ jobId: 'job-9' })
      if (u.includes('/drafting/jobs/')) {
        jobPolls.push(u)
        return ok(
          release
            ? { status: 'done', batch: 1, batchCount: 1, result: RESULT }
            : { status: 'running', batch: 1, batchCount: 1 },
        )
      }
      return ok(null)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderWizard()
    await screen.findByLabelText('路径')
    await userEvent.type(screen.getByLabelText('路径'), '/tmp/shop.db')
    await userEvent.click(screen.getByRole('button', { name: '读取表结构' }))
    await screen.findByText('customer')
    await userEvent.click(screen.getByRole('button', { name: '生成草稿' }))
    await waitFor(() => expect(jobPolls.length).toBeGreaterThanOrEqual(1))

    // close mid-poll, reopen a fresh session, then let the old job finish
    // (separate acts: a batched false→true would skip the closed→open reset)
    act(() => {
      useUiStore.getState().setDraftOpen(false)
    })
    await new Promise((r) => setTimeout(r, 50))
    act(() => {
      useUiStore.getState().setDraftOpen(true)
    })
    release = true
    // two poll cycles of silence: a live stale loop would fetch done and advance
    await new Promise((r) => setTimeout(r, 700))

    // the fresh session stays on step 1; the stale result never lands
    expect(screen.getByText('连接', { selector: '[data-step-name]' })).toBeTruthy()
    expect(screen.queryByText('hasCustomer')).toBeNull()
  })

  it('重新生成 returns to step 2 with the table selections kept', async () => {
    const { fetchMock } = step3Router()
    vi.stubGlobal('fetch', fetchMock)
    await atStep3()

    await userEvent.click(screen.getByRole('button', { name: '重新生成' }))

    expect(await screen.findByText('customer')).toBeTruthy()
    expect(screen.getByText('已选 2/500')).toBeTruthy()
    expect(screen.queryByText('hasCustomer')).toBeNull()
  })
})
