import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi, type Mock } from 'vitest'
import ConnectionsPanel from './ConnectionsPanel'

/* The Settings-page connections panel: list (no password material ever),
   create/edit dialog (edit: blank password keeps the stored ciphertext —
   PUT omits the key), per-row connect test (SELECT 1 via saved id), delete
   behind window.confirm. Port prefill rides on the engines registry. */

const ok = (data: unknown) =>
  new Response(JSON.stringify({ code: 'OK', message: 'ok', data, hint: null, request_id: 'r' }), {
    headers: { 'Content-Type': 'application/json' },
  })

const ENGINES = [
  { dbType: 'sqlite', label: 'SQLite', installed: true, defaultPort: null },
  { dbType: 'postgres', label: 'PostgreSQL', installed: true, defaultPort: 5432 },
  { dbType: 'mysql', label: 'MySQL', installed: false, defaultPort: 3306 },
]

const CONNS = [
  {
    id: 'c1',
    name: 'pg1',
    dbType: 'postgres',
    host: 'db.local',
    port: 5432,
    database: 'app',
    username: 'u',
    hasPassword: true,
    createdAt: '2026-10-01T00:00:00Z',
  },
  {
    id: 'c2',
    name: 'lite',
    dbType: 'sqlite',
    host: null,
    port: null,
    database: '/tmp/x.db',
    username: null,
    hasPassword: false,
    createdAt: '2026-10-02T00:00:00Z',
  },
]

/** Fetch mock routing the panel's three endpoints; extras fold into opts. */
function routerMock(
  opts: { conns?: unknown[]; engines?: unknown[]; testOk?: boolean; testMsg?: string } = {},
) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url)
    if (u.includes('/db-connections/engines')) return ok(opts.engines ?? ENGINES)
    if (u.includes('/db-connections/test') && init?.method === 'POST')
      return opts.testOk === false ? ok({ ok: false, message: opts.testMsg ?? 'boom' }) : ok({ ok: true })
    if (u.match(/\/db-connections\/[\w-]+$/) && init?.method === 'DELETE') return ok(null)
    if (u.match(/\/db-connections\/[\w-]+$/) && init?.method === 'PUT')
      return ok({ ...CONNS[0], ...JSON.parse(String(init.body)) })
    if (u.includes('/db-connections') && init?.method === 'POST')
      return ok({ ...CONNS[0], ...JSON.parse(String(init.body)) })
    if (u.includes('/db-connections')) return ok(opts.conns ?? CONNS)
    return ok(null)
  })
}

function bodies(fetchMock: Mock, needle: string) {
  return fetchMock.mock.calls
    .filter(([url, init]) => String(url).includes(needle) && init?.body)
    .map(([, init]) => JSON.parse(String(init.body)))
}

function renderPanel(fetchMock: Mock) {
  vi.stubGlobal('fetch', fetchMock)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ConnectionsPanel />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('ConnectionsPanel — 列表', () => {
  it('renders rows with target summaries and the no-password flag', async () => {
    const fetchMock = routerMock()
    renderPanel(fetchMock)
    expect(await screen.findByText('pg1')).toBeTruthy()
    // host:port/database for network engines, the bare path for sqlite
    expect(screen.getByText('db.local:5432/app')).toBeTruthy()
    expect(screen.getByText('/tmp/x.db')).toBeTruthy()
    // hasPassword=false flags the row; the encrypted one shows no warning
    expect(screen.getByText('无密码')).toBeTruthy()
  })

  it('shows the empty state when no connections exist', async () => {
    renderPanel(routerMock({ conns: [] }))
    expect(await screen.findByText('还没有已存连接')).toBeTruthy()
  })
})

describe('ConnectionsPanel — 新建', () => {
  it('creates a sqlite profile with path-only fields', async () => {
    const fetchMock = routerMock({ conns: [] })
    renderPanel(fetchMock)
    await userEvent.click(await screen.findByRole('button', { name: '新建连接' }))

    await userEvent.type(screen.getByLabelText('名称'), 'shop')
    // sqlite is the first installed engine → path field, no host/port
    await userEvent.type(screen.getByLabelText('路径'), '/data/shop.db')
    await userEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(bodies(fetchMock, '/db-connections')).toHaveLength(1))
    expect(bodies(fetchMock, '/db-connections')[0]).toEqual({
      name: 'shop',
      dbType: 'sqlite',
      database: '/data/shop.db',
    })
  })

  it('prefills the port from the engines registry when switching dbType', async () => {
    const fetchMock = routerMock({ conns: [] })
    renderPanel(fetchMock)
    await userEvent.click(await screen.findByRole('button', { name: '新建连接' }))

    const type = await screen.findByLabelText('数据库类型')
    await userEvent.selectOptions(type, 'postgres')
    expect((screen.getByLabelText('端口') as HTMLInputElement).value).toBe('5432')

    // switching back to sqlite drops the port along with the field
    await userEvent.selectOptions(type, 'sqlite')
    expect(screen.queryByLabelText('端口')).toBeNull()
  })

  it('tests raw form values without persisting anything', async () => {
    const fetchMock = routerMock({ conns: [] })
    renderPanel(fetchMock)
    await userEvent.click(await screen.findByRole('button', { name: '新建连接' }))

    await userEvent.type(screen.getByLabelText('名称'), 'shop')
    await userEvent.type(screen.getByLabelText('路径'), '/data/shop.db')
    await userEvent.click(screen.getByRole('button', { name: '测试连接' }))

    await waitFor(() => expect(bodies(fetchMock, '/db-connections/test')).toHaveLength(1))
    expect(bodies(fetchMock, '/db-connections/test')[0]).toMatchObject({
      dbType: 'sqlite',
      database: '/data/shop.db',
    })
    expect(bodies(fetchMock, '/db-connections/test')[0]).not.toHaveProperty('connectionId')
    expect(await screen.findByText('连接成功')).toBeTruthy()
  })
})

describe('ConnectionsPanel — 编辑与删除', () => {
  it('edits with prefilled fields; a blank password keeps the stored one (PUT omits the key)', async () => {
    const fetchMock = routerMock()
    renderPanel(fetchMock)
    await userEvent.click((await screen.findAllByRole('button', { name: '编辑' }))[0])

    // edit form prefills from the row (postgres: host/port/database/username)
    expect((screen.getByLabelText('主机') as HTMLInputElement).value).toBe('db.local')
    expect((screen.getByLabelText('库名') as HTMLInputElement).value).toBe('app')

    await userEvent.clear(screen.getByLabelText('主机'))
    await userEvent.type(screen.getByLabelText('主机'), 'db2.local')
    await userEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(bodies(fetchMock, '/db-connections/c1')).toHaveLength(1))
    const body = bodies(fetchMock, '/db-connections/c1')[0]
    expect(body.host).toBe('db2.local')
    expect(body).not.toHaveProperty('password')
  })

  it('blocks renaming to another connection’s name without a request', async () => {
    const fetchMock = routerMock()
    renderPanel(fetchMock)
    await userEvent.click((await screen.findAllByRole('button', { name: '编辑' }))[0])

    await userEvent.clear(screen.getByLabelText('名称'))
    await userEvent.type(screen.getByLabelText('名称'), 'lite') // c2's name
    await userEvent.click(screen.getByRole('button', { name: '保存' }))

    expect(await screen.findByText('名称已存在')).toBeTruthy()
    expect(bodies(fetchMock, '/db-connections/c1')).toHaveLength(0)
  })

  it('rejects a non-numeric port before any request leaves', async () => {
    const fetchMock = routerMock({
      conns: [],
      engines: ENGINES.map((e) => ({ ...e, installed: true })),
    })
    renderPanel(fetchMock)
    await userEvent.click(await screen.findByRole('button', { name: '新建连接' }))

    const type = await screen.findByLabelText('数据库类型')
    await screen.findByText(/PostgreSQL/)
    await userEvent.selectOptions(type, 'postgres')
    await userEvent.clear(screen.getByLabelText('端口'))
    await userEvent.type(screen.getByLabelText('端口'), 'abc')
    await userEvent.type(screen.getByLabelText('名称'), 'p9')
    await userEvent.type(screen.getByLabelText('主机'), 'h')
    await userEvent.type(screen.getByLabelText('库名'), 'd')
    await userEvent.click(screen.getByRole('button', { name: '保存' }))

    expect(await screen.findByText('端口必须是 1-65535 的数字')).toBeTruthy()
    const posts = fetchMock.mock.calls.filter(
      (c) => String(c[0]).endsWith('/db-connections') && c[1]?.method === 'POST',
    )
    expect(posts).toHaveLength(0)
  })

  it('tests a saved row by connectionId and reports failures inline', async () => {
    const fetchMock = routerMock({ testOk: false, testMsg: 'connection refused' })
    renderPanel(fetchMock)
    await userEvent.click((await screen.findAllByRole('button', { name: '测试' }))[0])

    await waitFor(() => expect(bodies(fetchMock, '/db-connections/test')).toHaveLength(1))
    expect(bodies(fetchMock, '/db-connections/test')[0]).toEqual({ connectionId: 'c1' })
    expect(await screen.findByText(/connection refused/)).toBeTruthy()
  })

  it('delete asks for confirmation, then DELETEs and refreshes', async () => {
    const fetchMock = routerMock()
    renderPanel(fetchMock)
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)

    await userEvent.click((await screen.findAllByRole('button', { name: '删除' }))[1])
    expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining('删除这条连接？'))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/db-connections/c2',
        expect.objectContaining({ method: 'DELETE' }),
      ),
    )
  })

  it('declining the confirmation sends no DELETE', async () => {
    const fetchMock = routerMock()
    renderPanel(fetchMock)
    vi.spyOn(window, 'confirm').mockReturnValue(false)

    await userEvent.click((await screen.findAllByRole('button', { name: '删除' }))[1])
    const deletes = fetchMock.mock.calls.filter((c) => c[1]?.method === 'DELETE')
    expect(deletes).toHaveLength(0)
  })
})
