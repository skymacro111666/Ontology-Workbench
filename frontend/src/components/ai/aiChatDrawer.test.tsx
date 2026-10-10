import { cleanup, render, screen } from '@testing-library/react'
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
  renderDrawer()
  await screen.findByText('AI 助手')
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
            createdAt: '2026-10-09T01:00:01Z',
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
})
