import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Envelope, LintReportT, OntologyMeta } from '../api/types'
import { useBrowseStore } from '../stores/browseStore'
import { ThemeProvider } from '../theme/ThemeProvider'
import LintPanel from './LintPanel'

/* The B3 surface: a manual 检查 button in the canvas controls, a
   severity-grouped bottom drawer, per-finding navigation, and a stale
   marker once the ontology's fileHash moves past the report. */

const OID = 'oid-1'
const SF = 'http://example.org/library#ScienceFiction'

const META = {
  id: OID,
  title: 'Mini',
  filename: 'mini.ttl',
  format: 'turtle',
  classCount: 1,
  propertyCount: 0,
  axiomCount: 3,
  instanceCount: 0,
  fileSizeBytes: 100,
  fileHash: 'h1',
  prefixes: { lib: 'http://example.org/library#' },
  createdAt: '2026-08-26T00:00:00',
} satisfies OntologyMeta

const REPORT: LintReportT = {
  fileHash: 'h1',
  durationMs: 12.5,
  counts: { error: 1, warning: 0, info: 0 },
  results: [
    {
      ruleId: 'disjoint-parents',
      name: null,
      severity: null,
      durationMs: 3.2,
      findings: [
        {
          ruleId: 'disjoint-parents',
          severity: 'error',
          subject: SF,
          subjectCurie: 'lib:ScienceFiction',
          params: { parent1: 'lib:A', parent2: 'lib:B' },
        },
      ],
      total: 1,
      truncated: false,
      error: null,
    },
    {
      ruleId: 'missing-label',
      name: null,
      severity: null,
      durationMs: 1.1,
      findings: [],
      total: 0,
      truncated: false,
      error: null,
    },
  ],
}

function env(data: unknown, code = 'OK') {
  return new Response(
    JSON.stringify({ code, message: 'ok', data, hint: null, request_id: 'r' } satisfies Envelope<unknown>),
    { headers: { 'Content-Type': 'application/json' } },
  )
}

interface CallLog {
  post: { url: string; body: Record<string, unknown> }[]
}

let calls: CallLog
let metaHash: string

function stubFetch() {
  calls = { post: [] }
  return vi.fn(async (url: string | URL, init?: RequestInit) => {
    const u = String(url)
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : {}
    if (method === 'POST') {
      calls.post.push({ url: u, body })
      return env(REPORT)
    }
    if (u.endsWith('/meta')) return env({ ...META, fileHash: metaHash })
    return env({})
  })
}

function draw(fetchMock: ReturnType<typeof stubFetch>) {
  vi.stubGlobal('fetch', fetchMock)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const view = render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        {/* The drawer positions absolutely within the canvas container. */}
        <div className="relative">
          <LintPanel oid={OID} />
        </div>
      </ThemeProvider>
    </QueryClientProvider>,
  )
  return { qc, ...view }
}

beforeEach(() => {
  metaHash = 'h1'
  useBrowseStore.setState({ selectedEid: null, revealEid: null })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('LintPanel', () => {
  it('runs lint on click and groups findings with navigation', async () => {
    draw(stubFetch())
    await userEvent.click(await screen.findByRole('button', { name: /检查/ }))
    // The drawer lands with the severity badge and the rule's local name.
    expect(await screen.findByText('错误 1')).toBeTruthy()
    expect(screen.getByText(/不相交父类/)).toBeTruthy()
    // The finding row pairs the subject chip with the templated message.
    const chip = screen.getByRole('button', { name: 'ScienceFiction' })
    expect(chip.title).toBe('lib:ScienceFiction')
    await userEvent.click(chip)
    expect(useBrowseStore.getState().selectedEid).toBe(SF)
    expect(calls.post[0].url).toBe(`/api/ontologies/${OID}/lint/run`)
  })

  it('marks results stale after the fileHash moves on', async () => {
    const { qc } = draw(stubFetch())
    await userEvent.click(await screen.findByRole('button', { name: /检查/ }))
    expect(await screen.findByText('错误 1')).toBeTruthy()
    expect(screen.queryByText(/已过期/)).toBeNull()
    // The ontology gets edited (hash bump); the meta refetch flips stale.
    metaHash = 'h2'
    await act(async () => {
      await qc.invalidateQueries({ queryKey: ['ontology', OID] })
    })
    expect(await screen.findByText(/已过期/)).toBeTruthy()
  })
})
