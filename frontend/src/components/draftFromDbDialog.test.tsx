import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
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
      <DraftFromDbDialog />
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

describe('DraftFromDbDialog — step 1 连接', () => {
  it('renders the dialog from the store flag with engines fetched', async () => {
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
