import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AiChatDrawer from './AiChatDrawer'
import { useUiStore } from '../../stores/uiStore'

const json = (data: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(data), {
    headers: { 'Content-Type': 'application/json', ...headers },
  })
const ok = (data: unknown) =>
  json({ code: 'OK', message: 'ok', data, hint: null, request_id: 'r' })

/** An SSE Response whose body is a ReadableStream over the given frames. */
function sseResponse(frames: string[]) {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const enc = new TextEncoder()
      for (const f of frames) controller.enqueue(enc.encode(f))
      controller.close()
    },
  })
  return new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } })
}

const frame = (event: string, data: unknown) =>
  `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`

const HAPPY = [
  frame('session', { sessionId: 'sid-1', title: '介绍一下' }),
  frame('tool_start', { name: 'search_entities', argsSummary: '{"q":"Cust","limit":20}' }),
  frame('tool_end', { name: 'search_entities', ok: true, summary: 'search_entities: 1 hit' }),
  frame('delta', { text: '这个本体有' }),
  frame('delta', { text: '两个核心类。' }),
  frame('done', { model: 'test-model', inTokens: 5, outTokens: 2, elapsedMs: 1200 }),
]

/** Drawer-open render with status/sessions pre-stubbed. */
function renderDrawer() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AiChatDrawer oid="oid-1" />
    </QueryClientProvider>,
  )
}

async function openDrawer(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal('fetch', fetchMock)
  useUiStore.getState().setAiChatOpen(true)
  const view = renderDrawer()
  await screen.findByText('AI 助手')
  return view
}

beforeEach(() => {
  localStorage.clear()
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  useUiStore.getState().setAiChatOpen(false)
})

describe('AiChatDrawer', () => {
  it('streams a conversation: deltas concat, tool row expands, usage footer lands', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      const u = String(url)
      if (u.includes('/ai/status')) return ok({ configured: true, provider: 'openai', model: 'test-model', source: 'env' })
      if (u.includes('/chat/sessions')) return ok([])
      if (u.includes('/chat/messages')) return sseResponse(HAPPY)
      return ok(null)
    })
    await openDrawer(fetchMock)

    await userEvent.type(screen.getByPlaceholderText('问点什么,如:哪些类没有实例?'), '介绍一下{Enter}')

    // typewriter deltas concatenated into one assistant bubble
    expect(await screen.findByText('这个本体有两个核心类。')).toBeTruthy()

    // tool row: collapsed, click expands the args JSON
    const toolBtn = screen.getByRole('button', { name: /search_entities/ })
    expect(toolBtn).toBeTruthy()
    await userEvent.click(toolBtn)
    expect(screen.getByText(/"q":"Cust"/)).toBeTruthy()

    // usage footer
    expect(screen.getByText('test-model · in 5 / out 2 · 1.2s')).toBeTruthy()
  })

  it('shows the stop button while streaming and finishes when the stream closes', async () => {
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    const fetchMock = vi.fn(async (url: string) => {
      const u = String(url)
      if (u.includes('/ai/status')) return ok({ configured: true, provider: 'openai', model: 'm', source: 'env' })
      if (u.includes('/chat/sessions')) return ok([])
      if (u.includes('/chat/messages')) {
        const stream = new ReadableStream<Uint8Array>({
          async start(controller) {
            const enc = new TextEncoder()
            controller.enqueue(enc.encode(frame('session', { sessionId: 'sid-1', title: '慢问题' })))
            await gate
            controller.enqueue(enc.encode(frame('delta', { text: '迟到的回答。' })))
            controller.enqueue(enc.encode(frame('done', { model: 'm', inTokens: 1, outTokens: 1, elapsedMs: 50 })))
            controller.close()
          },
        })
        return new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } })
      }
      return ok(null)
    })
    await openDrawer(fetchMock)

    await userEvent.type(screen.getByPlaceholderText('问点什么,如:哪些类没有实例?'), '慢问题{Enter}')
    expect(await screen.findByRole('button', { name: '停止' })).toBeTruthy()
    release()
    expect(await screen.findByText('迟到的回答。')).toBeTruthy()
  })

  it('renders the unconfigured guide card and 去配置 opens the AI settings dialog', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      const u = String(url)
      if (u.includes('/ai/status')) return ok({ configured: false, provider: null, model: null, source: 'env' })
      if (u.includes('/chat/messages')) {
        return json({ code: 'AI_NOT_CONFIGURED', message: 'AI provider is not configured', data: null, hint: null, request_id: 'r' })
      }
      return ok([])
    })
    await openDrawer(fetchMock)

    await userEvent.type(screen.getByPlaceholderText('问点什么,如:哪些类没有实例?'), '你好{Enter}')

    expect(await screen.findByText('AI 未配置')).toBeTruthy()
    expect(screen.getByText(/AI_MODEL_PROVIDER/)).toBeTruthy()
    useUiStore.getState().setAiSettingsOpen(false)
    await userEvent.click(screen.getByRole('button', { name: '去配置' }))
    expect(useUiStore.getState().aiSettingsOpen).toBe(true)
  })

  it('loads the latest session history on open and renders stored tool rows', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      const u = String(url)
      if (u.includes('/ai/status')) return ok({ configured: true, provider: 'openai', model: 'm', source: 'env' })
      if (u.includes('/chat/sessions/')) {
        return ok([
          { id: 1, role: 'user', content: '旧问题', createdAt: '2026-10-09T01:00:00Z' },
          {
            id: 2,
            role: 'tool',
            content: JSON.stringify({ name: 'get_ontology', ok: true, result: '{"classCount":2}' }),
            createdAt: '2026-10-09T01:00:02Z',
          },
          { id: 3, role: 'assistant', content: '旧回答。', createdAt: '2026-10-09T01:00:02Z' },
        ])
      }
      if (u.includes('/chat/sessions')) {
        return ok([{ id: 'sid-1', title: '旧会话', updatedAt: '2026-10-09T01:00:02Z', messageCount: 3 }])
      }
      return ok(null)
    })
    await openDrawer(fetchMock)

    expect(await screen.findByText('旧问题')).toBeTruthy()
    expect(screen.getByText('旧回答。')).toBeTruthy()
    // stored tool row expands to its persisted result JSON
    const toolBtn = await screen.findByRole('button', { name: /get_ontology/ })
    await userEvent.click(toolBtn)
    expect(screen.getByText(/"classCount":2/)).toBeTruthy()
  })

  it('clears a dead session pointer when the next send 404s', async () => {
    let posts = 0
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      const u = String(url)
      if (u.includes('/ai/status')) return ok({ configured: true, provider: 'openai', model: 'm', source: 'env' })
      if (u.includes('/chat/sessions')) return ok([])
      if (init?.method === 'POST' && u.includes('/chat/messages')) {
        posts += 1
        return posts === 1
          ? sseResponse(HAPPY)
          : json({ code: 'NOT_FOUND', message: 'No such session', data: null, hint: null, request_id: 'r' })
      }
      return ok(null)
    })
    await openDrawer(fetchMock)
    await userEvent.type(screen.getByPlaceholderText('问点什么,如:哪些类没有实例?'), '第一问{Enter}')
    await screen.findByText('这个本体有两个核心类。')
    expect(localStorage.getItem('ow.chat.session.oid-1')).toBe('sid-1')

    await userEvent.type(screen.getByPlaceholderText('问点什么,如:哪些类没有实例?'), '第二问{Enter}')
    expect(await screen.findByText(/No such session/)).toBeTruthy()
    // the dead pointer is dropped — the next send lazy-creates instead of 404ing forever
    expect(localStorage.getItem('ow.chat.session.oid-1')).toBeNull()
  })

  it('does not send on an IME composition Enter', async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      const u = String(url)
      if (u.includes('/ai/status')) return ok({ configured: true, provider: 'openai', model: 'm', source: 'env' })
      if (u.includes('/chat/sessions')) return ok([])
      if (init?.method === 'POST' && u.includes('/chat/messages')) return sseResponse(HAPPY)
      return ok(null)
    })
    await openDrawer(fetchMock)
    const ta = screen.getByPlaceholderText('问点什么,如:哪些类没有实例?')
    const posts = () =>
      fetchMock.mock.calls.filter(
        ([u, i]) => String(u).includes('/chat/messages') && (i as RequestInit | undefined)?.method === 'POST',
      )

    await userEvent.type(ta, '哪些类没有实例')
    fireEvent.keyDown(ta, { key: 'Enter', isComposing: true }) // IME confirm, not a send
    await waitFor(() => expect(posts()).toHaveLength(0))

    await userEvent.type(ta, '{Enter}') // the real one sends
    expect(await screen.findByText('这个本体有两个核心类。')).toBeTruthy()
    expect(posts()).toHaveLength(1)
    expect((JSON.parse(String((posts()[0]![1] as RequestInit).body)) as { content: string }).content).toBe(
      '哪些类没有实例',
    )
  })

  it('renders fenced code blocks as <pre>', async () => {
    const fenced = [
      frame('session', { sessionId: 'sid-1', title: '查询' }),
      frame('delta', {
        text: '查询如下:\n```sparql\nSELECT ?s WHERE { ?s ?p ?o }\n```\n共 2 个类。',
      }),
      frame('done', { model: 'm', inTokens: 1, outTokens: 1, elapsedMs: 10 }),
    ]
    const fetchMock = vi.fn(async (url: string) => {
      const u = String(url)
      if (u.includes('/ai/status')) return ok({ configured: true, provider: 'openai', model: 'm', source: 'env' })
      if (u.includes('/chat/sessions')) return ok([])
      if (u.includes('/chat/messages')) return sseResponse(fenced)
      return ok(null)
    })
    const { container } = (await openDrawer(fetchMock)) as { container: HTMLElement }

    await userEvent.type(screen.getByPlaceholderText('问点什么,如:哪些类没有实例?'), '查询{Enter}')
    await screen.findByText(/共 2 个类。/)
    const pre = container.querySelector('pre')
    expect(pre?.textContent).toContain('SELECT ?s WHERE { ?s ?p ?o }')
    expect(pre?.textContent).not.toContain('```')
    expect(pre?.textContent).not.toContain('sparql\n') // language tag stripped
  })
})

describe('AiChatDrawer session menu', () => {
  const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString()
  const SESSIONS = [
    { id: 'sid-a', title: '介绍一下这个本体', updatedAt: ago(2), messageCount: 3 },
    { id: 'sid-b', title: 'Publication 和 Course 的关系', updatedAt: ago(26 * 60), messageCount: 7 },
  ]
  const ROWS_A = [
    { id: 1, role: 'user', content: '问题A', createdAt: ago(2) },
    { id: 2, role: 'assistant', content: '回答A。', createdAt: ago(2) },
  ]
  const ROWS_B = [
    { id: 3, role: 'user', content: '问题B', createdAt: ago(26 * 60) },
    { id: 4, role: 'assistant', content: '回答B。', createdAt: ago(26 * 60) },
  ]

  /** Sessions-capable stub: list + per-session messages + SSE on POST. */
  function stub(overrides?: {
    sessions?: typeof SESSIONS | null
    onMessages?: (sid: string) => typeof ROWS_A | typeof ROWS_B
  }) {
    return vi.fn(async (url: string, init?: RequestInit) => {
      const u = String(url)
      if (u.includes('/ai/status')) return ok({ configured: true, provider: 'openai', model: 'm', source: 'env' })
      if (init?.method === 'POST' && u.includes('/chat/messages')) return sseResponse(HAPPY)
      const m = u.match(/\/chat\/sessions\/([^/]+)\/messages$/)
      if (m) return ok((overrides?.onMessages?.(m[1]) ?? (m[1] === 'sid-b' ? ROWS_B : ROWS_A)) as unknown)
      if (u.includes('/chat/sessions')) return ok(overrides?.sessions === null ? [] : (overrides?.sessions ?? SESSIONS))
      return ok(null)
    })
  }
  const openMenu = async () => {
    await userEvent.click(screen.getByRole('button', { name: '会话列表' }))
    await screen.findByText('会话')
  }

  it('shows the active session in the header segment', async () => {
    await openDrawer(stub())
    expect(await screen.findByText('问题A')).toBeTruthy()
    // header segment: active title + message count + relative time
    expect(screen.getByText('介绍一下这个本体')).toBeTruthy()
    expect(screen.getByText(/3 条消息/)).toBeTruthy()
    expect(screen.getByText(/2 分钟前/)).toBeTruthy()
  })

  it('lists sessions with relative times in the history menu', async () => {
    await openDrawer(stub())
    expect(await screen.findByText('问题A')).toBeTruthy()
    await openMenu()
    expect(screen.getByText('Publication 和 Course 的关系')).toBeTruthy()
    expect(screen.getByText(/2 分钟前 · 3 条/)).toBeTruthy()
    expect(screen.getByText(/1 天前 · 7 条/)).toBeTruthy()
  })

  it('switches sessions from the menu row', async () => {
    const fetchMock = stub()
    await openDrawer(fetchMock)
    expect(await screen.findByText('问题A')).toBeTruthy()
    await openMenu()
    await userEvent.click(screen.getByText('Publication 和 Course 的关系'))
    expect(await screen.findByText('问题B')).toBeTruthy()
    expect(screen.getByText('回答B。')).toBeTruthy()
    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes('/chat/sessions/sid-b/messages'))).toBe(true)
    // pointer follows the switch
    expect(localStorage.getItem('ow.chat.session.oid-1')).toBe('sid-b')
  })

  it('opens the pointed session, not the newest', async () => {
    localStorage.setItem('ow.chat.session.oid-1', 'sid-b')
    await openDrawer(stub())
    expect(await screen.findByText('回答B。')).toBeTruthy()
    expect(screen.queryByText('回答A。')).toBeNull()
  })

  it('新对话 empties the view and the next send omits sessionId', async () => {
    const fetchMock = stub()
    await openDrawer(fetchMock)
    expect(await screen.findByText('问题A')).toBeTruthy()
    expect(localStorage.getItem('ow.chat.session.oid-1')).toBe('sid-a')
    await openMenu()
    await userEvent.click(screen.getByRole('button', { name: '新对话' }))
    expect(await screen.findByText('问点什么开始对话——只读助手可以搜实体、查结构、跑检查')).toBeTruthy()
    expect(localStorage.getItem('ow.chat.session.oid-1')).toBeNull()

    await userEvent.type(screen.getByPlaceholderText('问点什么,如:哪些类没有实例?'), '新问题{Enter}')
    await screen.findByText('这个本体有两个核心类。')
    const sent = fetchMock.mock.calls.find(
      (c) => String(c[0]).includes('/chat/messages') && (c[1] as RequestInit | undefined)?.method === 'POST',
    )
    expect(JSON.parse(String((sent?.[1] as RequestInit).body))).not.toHaveProperty('sessionId')
  })

  it('stores the session pointer when the stream opens a session', async () => {
    const fetchMock = stub({ sessions: [] })
    await openDrawer(fetchMock)
    await userEvent.type(screen.getByPlaceholderText('问点什么,如:哪些类没有实例?'), '介绍一下{Enter}')
    await screen.findByText('这个本体有两个核心类。')
    expect(localStorage.getItem('ow.chat.session.oid-1')).toBe('sid-1')
  })

  it('renames via inline input (PUT {title}) and refreshes the list', async () => {
    const fetchMock = stub()
    await openDrawer(fetchMock)
    expect(await screen.findByText('问题A')).toBeTruthy()
    await openMenu()
    const rows = screen.getAllByText('介绍一下这个本体') // header + menu row
    expect(rows.length).toBe(2)
    await userEvent.click(screen.getAllByRole('button', { name: '重命名' })[0]!) // first row (sid-a)
    const input = screen.getByDisplayValue('介绍一下这个本体')
    await userEvent.clear(input)
    await userEvent.type(input, '新标题')
    await userEvent.click(screen.getByRole('button', { name: '确认' }))
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([u, i]) => String(u).includes('/chat/sessions/sid-a') && i?.method === 'PUT')).toBe(true),
    )
    const put = fetchMock.mock.calls.find(([u, i]) => String(u).includes('/chat/sessions/sid-a') && i?.method === 'PUT')!
    expect(JSON.parse(String(put[1]!.body))).toEqual({ title: '新标题' })
  })

  it('deletes a session after AlertDialog confirm and refreshes the list', async () => {
    const fetchMock = stub()
    await openDrawer(fetchMock)
    expect(await screen.findByText('问题A')).toBeTruthy()
    await openMenu()
    await userEvent.click(screen.getAllByRole('button', { name: '删除' })[1]!) // second row
    expect(await screen.findByText('删除会话')).toBeTruthy()
    await userEvent.click(screen.getByRole('button', { name: '确认删除' }))
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([u, i]) => String(u).includes('/chat/sessions/sid-b') && i?.method === 'DELETE')).toBe(true),
    )
    // list re-fetched after the delete
    const listCalls = fetchMock.mock.calls.filter(([u, i]) => String(u).endsWith('/chat/sessions') && !i?.method)
    expect(listCalls.length).toBeGreaterThanOrEqual(2)
  })

  it('deleting the active session empties the drawer and clears the pointer', async () => {
    const fetchMock = stub()
    await openDrawer(fetchMock)
    expect(await screen.findByText('问题A')).toBeTruthy()
    expect(localStorage.getItem('ow.chat.session.oid-1')).toBe('sid-a')
    await openMenu()
    await userEvent.click(screen.getAllByRole('button', { name: '删除' })[0]!) // active row
    await userEvent.click(await screen.findByRole('button', { name: '确认删除' }))
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([u, i]) => String(u).includes('/chat/sessions/sid-a') && i?.method === 'DELETE')).toBe(true),
    )
    expect(await screen.findByText('问点什么开始对话——只读助手可以搜实体、查结构、跑检查')).toBeTruthy()
    expect(localStorage.getItem('ow.chat.session.oid-1')).toBeNull()
  })
})
