import { Loader2Icon, PlusIcon, SendIcon, SettingsIcon, SparklesIcon, SquareIcon } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ApiErr, api, streamSSE } from '../../api/client'
import type { AiStatus, ChatMessageRow, ChatSessionSummary } from '../../api/types'
import { useUiStore } from '../../stores/uiStore'
import SessionMenu, { timeAgoLabel } from './SessionMenu'
import { cn } from '@/lib/utils'

/** One collapsible tool row (mockup .tool): live rows carry the args JSON,
 *  history-loaded rows carry the persisted result JSON. */
interface ToolRow {
  name: string
  ok: boolean
  summary?: string
  argsSummary?: string
  result?: string
  open: boolean
}

interface Usage {
  model?: string
  inTokens: number
  outTokens: number
  elapsedMs: number
}

interface ChatMsg {
  role: 'user' | 'assistant'
  content: string
  tools?: ToolRow[]
  usage?: Usage
  error?: string
}

/** The read-only AI assistant drawer (spec-2 §5, approved mockup layout):
 *  header pills + message stream with collapsed tool rows + usage footer +
 *  send/stop input. Sessions land in the next task. */
export default function AiChatDrawer({ oid }: { oid: string }) {
  const { t } = useTranslation()
  const open = useUiStore((s) => s.aiChatOpen)
  const setAiChatOpen = useUiStore((s) => s.setAiChatOpen)
  const setAiSettingsOpen = useUiStore((s) => s.setAiSettingsOpen)

  const [messages, setMessages] = useState<ChatMsg[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [unconfigured, setUnconfigured] = useState(false)
  const [sid, setSid] = useState<string | null>(null)
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([])
  const abortRef = useRef<AbortController | null>(null)
  const bodyRef = useRef<HTMLDivElement>(null)

  // The active session persists per ontology: the pointer feeds send
  // (sessionId) and survives drawer close/reopen.
  const pointerKey = `ow.chat.session.${oid}`
  const setActive = useCallback(
    (id: string | null) => {
      setSid(id)
      if (id) localStorage.setItem(pointerKey, id)
      else localStorage.removeItem(pointerKey)
    },
    [pointerKey],
  )
  const reloadSessions = useCallback(async () => {
    try {
      setSessions(await api.get<ChatSessionSummary[]>(`/api/v1/ontologies/${oid}/chat/sessions`))
    } catch {
      /* the menu simply keeps its previous rows */
    }
  }, [oid])
  const loadSession = useCallback(
    async (id: string) => {
      const rows = await api.get<ChatMessageRow[]>(
        `/api/v1/ontologies/${oid}/chat/sessions/${id}/messages`,
      )
      setActive(id)
      setMessages(fromHistory(rows))
    },
    [oid, setActive],
  )

  const status = useQuery({
    queryKey: ['ai-status'],
    queryFn: () => api.get<AiStatus>('/api/v1/ai/status'),
    enabled: open,
  })

  // Open (re)load: the pointed session if it still exists, else the newest,
  // else empty (spec §5 — pointer wins over recency).
  useEffect(() => {
    if (!oid) return
    let alive = true
    ;(async () => {
      try {
        const list = await api.get<ChatSessionSummary[]>(`/api/v1/ontologies/${oid}/chat/sessions`)
        if (!alive) return
        setSessions(list)
        const pointer = localStorage.getItem(pointerKey)
        const target = list.find((s) => s.id === pointer) ?? list[0]
        if (target) await loadSession(target.id)
      } catch {
        /* leave the drawer empty — sending will surface errors inline */
      }
    })()
    return () => {
      alive = false
    }
  }, [oid, open, pointerKey, loadSession])

  // Keep the stream pinned to the bottom as deltas arrive.
  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight })
  }, [messages])

  const send = async () => {
    const content = input.trim()
    if (!content || streaming) return
    setInput('')
    setUnconfigured(false)
    setMessages((prev) => [...prev, { role: 'user', content }, { role: 'assistant', content: '' }])
    setStreaming(true)
    const abort = new AbortController()
    abortRef.current = abort
    try {
      await streamSSE(
        `/api/v1/ontologies/${oid}/chat/messages`,
        { sessionId: sid ?? undefined, content },
        (event, data) => {
          if (event === 'session') {
            setActive(String(data.sessionId))
            void reloadSessions()
          } else if (event === 'delta') {
            setMessages((prev) => patchLast(prev, (m) => ({ ...m, content: m.content + String(data.text) })))
          } else if (event === 'tool_start') {
            setMessages((prev) =>
              patchLast(prev, (m) => ({
                ...m,
                tools: [
                  ...(m.tools ?? []),
                  { name: String(data.name), ok: true, argsSummary: String(data.argsSummary ?? ''), open: false },
                ],
              })),
            )
          } else if (event === 'tool_end') {
            setMessages((prev) =>
              patchLast(prev, (m) => ({
                ...m,
                tools: (m.tools ?? []).map((tool) =>
                  tool.name === data.name && !tool.summary
                    ? { ...tool, ok: Boolean(data.ok), summary: String(data.summary ?? '') }
                    : tool,
                ),
              })),
            )
          } else if (event === 'done') {
            setMessages((prev) =>
              patchLast(prev, (m) => ({
                ...m,
                usage: {
                  model: data.model ? String(data.model) : undefined,
                  inTokens: Number(data.inTokens ?? 0),
                  outTokens: Number(data.outTokens ?? 0),
                  elapsedMs: Number(data.elapsedMs ?? 0),
                },
              })),
            )
          } else if (event === 'error') {
            setMessages((prev) => patchLast(prev, (m) => ({ ...m, error: String(data.message ?? data.code) })))
          }
        },
        abort.signal,
      )
    } catch (e) {
      if (e instanceof ApiErr && e.code === 'AI_NOT_CONFIGURED') setUnconfigured(true)
      else if (e instanceof ApiErr && e.code === 'NOT_FOUND') {
        // Dead pointer — the session rolled back or vanished elsewhere.
        // Drop it so the next send lazy-creates instead of 404ing forever.
        setActive(null)
        setMessages((prev) => patchLast(prev, (m) => ({ ...m, error: e.message })))
      } else if (!(e instanceof DOMException && e.name === 'AbortError')) {
        setMessages((prev) => patchLast(prev, (m) => ({ ...m, error: e instanceof Error ? e.message : String(e) })))
      }
    } finally {
      setStreaming(false)
      abortRef.current = null
    }
  }

  if (!open) return null

  const activeSession = sessions.find((s) => s.id === sid) ?? null

  // Session menu wiring — data ops live here, SessionMenu is presentational.
  const handleSwitch = (s: ChatSessionSummary) => void loadSession(s.id)
  const handleNew = () => {
    setMessages([])
    setActive(null)
  }
  const handleRename = async (s: ChatSessionSummary, title: string) => {
    await api.put(`/api/v1/ontologies/${oid}/chat/sessions/${s.id}`, { title })
    await reloadSessions()
  }
  const handleDelete = async (s: ChatSessionSummary) => {
    await api.del(`/api/v1/ontologies/${oid}/chat/sessions/${s.id}`)
    if (sid === s.id) {
      setMessages([])
      setActive(null)
    }
    await reloadSessions()
  }

  const model = status.data?.model || t('chatPanel.modelFallback')
  return (
    <div className="border-line bg-panel flex h-full min-h-0 flex-col border-l">
      {/* header: title + read-only pill + model pill + gear + close */}
      <div className="border-line flex items-center gap-2 border-b px-3 py-2.5">
        <span className="flex items-center gap-1.5 text-[13px] font-bold">
          <SparklesIcon aria-hidden="true" className="text-primary size-3.5" />
          {t('chatPanel.title')}
        </span>
        <span className="border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400 rounded-full border px-2 py-px text-[10px] font-semibold">
          {t('chatPanel.readOnly')}
        </span>
        <span className="border-line bg-panel-2 text-ink-2 rounded-full border px-2 py-px font-mono text-[10px] font-medium">
          {model}
        </span>
        <button
          type="button"
          aria-label={t('aiSettings.title')}
          onClick={() => setAiSettingsOpen(true)}
          className="text-ink-3 hover:text-ink hover:bg-panel-2 ml-auto rounded-ctl p-1"
        >
          <SettingsIcon aria-hidden="true" className="size-3.5" />
        </button>
        <button
          type="button"
          aria-label={t('common.close')}
          onClick={() => setAiChatOpen(false)}
          className="text-ink-3 hover:text-ink hover:bg-panel-2 rounded-ctl p-1"
        >
          <SquareIcon aria-hidden="true" className="size-3.5" />
        </button>
      </div>

      {/* session segment (mockup 会话管理): active title + history menu +
       *  new-chat — the row lands on the first message of a fresh session. */}
      <div className="border-line flex items-center gap-2 border-b px-3 py-1.5">
        <span className="min-w-0 flex-1">
          <b className="text-ink block truncate text-[12px] font-semibold">
            {activeSession?.title ?? t('chatPanel.newChat')}
          </b>
          {activeSession && (
            <small className="text-ink-3 block truncate text-[10px]">
              {t('chatPanel.headerMeta', {
                n: activeSession.messageCount,
                time: timeAgoLabel(t, activeSession.updatedAt),
              })}
            </small>
          )}
        </span>
        <SessionMenu
          sessions={sessions}
          activeId={sid}
          onSwitch={handleSwitch}
          onNew={handleNew}
          onRename={handleRename}
          onDelete={handleDelete}
        />
        <button
          type="button"
          aria-label={t('chatPanel.newChat')}
          title={t('chatPanel.newChat')}
          onClick={handleNew}
          className="border-line text-ink-2 hover:bg-panel-2 hover:text-ink inline-flex items-center rounded-ctl border bg-transparent p-1"
        >
          <PlusIcon aria-hidden="true" className="size-3.5" />
        </button>
      </div>

      {/* message stream */}
      <div ref={bodyRef} className="flex min-h-0 flex-1 flex-col gap-2.5 overflow-auto p-3">
        {messages.length === 0 && !unconfigured && (
          <p className="text-ink-3 py-8 text-center text-xs">{t('chatPanel.emptyHint')}</p>
        )}
        {messages.map((m, i) => (
          <div key={i} className="flex flex-col gap-1.5">
            {m.tools?.map((tool, j) => (
              <div
                key={j}
                className={cn(
                  'border-line bg-panel overflow-hidden rounded-ctl border text-[11.5px]',
                  tool.open && 'w-full',
                )}
              >
                <button
                  type="button"
                  aria-label={`${t('chatPanel.toolCall')} ${tool.name}`}
                  aria-expanded={tool.open}
                  onClick={() =>
                    setMessages((prev) =>
                      prev.map((msg, mi) =>
                        mi === i
                          ? {
                              ...msg,
                              tools: msg.tools?.map((tt, tj) => (tj === j ? { ...tt, open: !tt.open } : tt)),
                            }
                          : msg,
                      ),
                    )
                  }
                  className="text-ink-2 hover:bg-panel-2 flex w-full items-center gap-2 px-2.5 py-1.5 text-left"
                >
                  <span className="text-ink-3 text-[10px]">▸</span>
                  <span className="text-ink font-mono text-[11px]">{tool.name}</span>
                  <span className={tool.ok ? 'text-success text-[10.5px] font-bold' : 'text-destructive text-[10.5px] font-bold'}>
                    {tool.ok ? '✓' : '✕'}
                  </span>
                  {tool.summary && (
                    <span className="text-ink-3 ml-auto max-w-[60%] truncate text-[10.5px]">{tool.summary}</span>
                  )}
                </button>
                {tool.open && (
                  <pre className="border-line bg-panel-2 text-ink-2 max-h-40 overflow-auto border-t px-2.5 py-2 font-mono text-[10.5px] whitespace-pre-wrap">
                    {tool.result ?? tool.argsSummary ?? ''}
                  </pre>
                )}
              </div>
            ))}
            {m.role === 'user' ? (
              <div className="bg-primary text-primary-foreground max-w-[92%] self-end rounded-[10px] rounded-br-sm px-3 py-2 text-[12.5px]">
                {m.content}
              </div>
            ) : (
              (m.content || m.error) && (
                <div className="border-line bg-panel-2 text-ink max-w-[92%] self-start rounded-[10px] rounded-bl-sm border px-3 py-2 text-[12.5px]">
                  <MarkdownBody content={m.content} />
                  {m.error && <p className="text-destructive mt-1 text-[11.5px]">{m.error}</p>}
                </div>
              )
            )}
            {m.usage && (
              <div className="text-ink-3 self-start font-mono text-[10px]">
                {t('chatPanel.usage', {
                  model: m.usage.model || model,
                  in: m.usage.inTokens,
                  out: m.usage.outTokens,
                  sec: (m.usage.elapsedMs / 1000).toFixed(1),
                })}
              </div>
            )}
          </div>
        ))}
        {streaming && (
          <div className="text-primary flex items-center gap-1.5 self-start px-1 text-[11px]">
            <Loader2Icon aria-hidden="true" className="size-3 animate-spin" />
          </div>
        )}
        {unconfigured && (
          <div className="border-amber-500/40 bg-amber-500/10 text-ink flex flex-col gap-2 rounded-ctl border p-3 text-xs">
            <b>{t('chatPanel.unconfiguredTitle')}</b>
            <pre className="text-ink-2 font-mono text-[10.5px]">AI_MODEL_PROVIDER=openai
AI_BASE_URL=https://api.deepseek.com/v1
AI_API_KEY=sk-***
AI_MODEL=deepseek-chat</pre>
            <button
              type="button"
              onClick={() => setAiSettingsOpen(true)}
              className="border-line bg-panel text-ink self-start rounded-ctl border px-2.5 py-1 text-[11.5px] font-medium"
            >
              {t('chatPanel.goSettings')}
            </button>
          </div>
        )}
      </div>

      {/* input */}
      <div className="border-line border-t p-2.5">
        <div className="border-line bg-panel flex items-end gap-2 rounded-ctl border p-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.nativeEvent.isComposing) return // IME confirm Enter, not a send
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                void send()
              }
            }}
            placeholder={t('chatPanel.placeholder')}
            rows={2}
            className="text-ink placeholder:text-ink-3 max-h-28 flex-1 resize-none bg-transparent text-xs outline-none"
          />
          {streaming ? (
            <button
              type="button"
              onClick={() => abortRef.current?.abort()}
              aria-label={t('chatPanel.stop')}
              className="shrink-0 rounded-ctl bg-amber-500 px-2.5 py-1.5 text-white"
              title={t('chatPanel.stop')}
            >
              <SquareIcon aria-hidden="true" className="size-3.5" />
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void send()}
              aria-label={t('chatPanel.send')}
              disabled={!input.trim()}
              className="bg-primary text-primary-foreground disabled:opacity-40 shrink-0 rounded-ctl px-2.5 py-1.5"
              title={t('chatPanel.send')}
            >
              <SendIcon aria-hidden="true" className="size-3.5" />
            </button>
          )}
        </div>
        <div className="text-ink-3 mt-1.5 flex items-center justify-between px-1 text-[10px]">
          <span>{t('chatPanel.enterHint')}</span>
          <span>{t('chatPanel.llmNote')}</span>
        </div>
      </div>
    </div>
  )
}

/** Mutate the last message (the streaming assistant bubble). */
function patchLast(prev: ChatMsg[], fn: (m: ChatMsg) => ChatMsg): ChatMsg[] {
  if (prev.length === 0) return prev
  const next = [...prev]
  next[next.length - 1] = fn(next[next.length - 1])
  return next
}

/** Assistant message body: GFM Markdown (headings, bold, lists, tables,
 *  fenced code) mapped onto house tokens. react-markdown renders no raw
 *  HTML by default, keeping LLM output outside the DOM injection surface;
 *  links open in a new tab. Code styling lives on the `pre` override so
 *  inline code shares one mono look without nested chrome. */
const MD_COMPONENTS: Components = {
  h1: ({ children }) => <h1 className="mb-1 mt-2 text-[14px] font-bold">{children}</h1>,
  h2: ({ children }) => <h2 className="mb-1 mt-2 text-[13.5px] font-bold">{children}</h2>,
  h3: ({ children }) => <h3 className="mb-1 mt-1.5 text-[13px] font-semibold">{children}</h3>,
  h4: ({ children }) => <h4 className="mb-1 mt-1.5 text-[12.5px] font-semibold">{children}</h4>,
  p: ({ children }) => <p className="my-1 leading-relaxed">{children}</p>,
  ul: ({ children }) => <ul className="my-1 list-disc pl-4">{children}</ul>,
  ol: ({ children }) => <ol className="my-1 list-decimal pl-4">{children}</ol>,
  li: ({ children }) => <li className="my-0.5">{children}</li>,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noreferrer" className="text-primary underline">
      {children}
    </a>
  ),
  blockquote: ({ children }) => (
    <blockquote className="border-line text-ink-2 my-1 border-l-2 pl-2">{children}</blockquote>
  ),
  hr: () => <hr className="border-line my-2 border-t" />,
  pre: ({ children }) => (
    <pre className="border-line bg-panel text-ink my-1 max-w-full overflow-x-auto rounded-ctl border px-2.5 py-2 font-mono text-[11px] whitespace-pre">
      {children}
    </pre>
  ),
  code: ({ children }) => <code className="font-mono text-[11.5px]">{children}</code>,
  table: ({ children }) => (
    <div className="border-line my-1.5 overflow-x-auto rounded-ctl border">
      <table className="w-full border-collapse text-[11.5px]">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border-line bg-panel px-2 py-1 text-left font-semibold">{children}</th>
  ),
  td: ({ children }) => <td className="border-line px-2 py-1 align-top">{children}</td>,
}

function MarkdownBody({ content }: { content: string }) {
  return (
    <div className="markdown-body">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_COMPONENTS}>
        {content}
      </ReactMarkdown>
    </div>
  )
}

/** History rows → ChatMsg[]: stored tool rows re-render collapsed with their
 *  persisted result JSON; they attach to the assistant turn that follows. */
function fromHistory(rows: ChatMessageRow[]): ChatMsg[] {
  const out: ChatMsg[] = []
  let pending: ToolRow[] = []
  for (const r of rows) {
    if (r.role === 'tool') {
      try {
        const j = JSON.parse(r.content) as { name?: string; ok?: boolean; result?: string }
        pending.push({ name: j.name ?? 'tool', ok: j.ok ?? true, result: j.result ?? '', open: false })
      } catch {
        pending.push({ name: 'tool', ok: true, result: r.content, open: false })
      }
    } else if (r.role === 'assistant') {
      out.push({ role: 'assistant', content: r.content, tools: pending })
      pending = []
    } else {
      if (pending.length) out.push({ role: 'assistant', content: '', tools: pending })
      pending = []
      out.push({ role: 'user', content: r.content })
    }
  }
  if (pending.length) out.push({ role: 'assistant', content: '', tools: pending })
  return out
}
