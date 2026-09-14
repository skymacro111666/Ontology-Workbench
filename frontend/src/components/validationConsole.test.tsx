import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Envelope, OntologyMeta } from '../api/types'
import { useBrowseStore } from '../stores/browseStore'
import { useUiStore } from '../stores/uiStore'
import { ThemeProvider } from '../theme/ThemeProvider'
import ValidationConsole from './ValidationConsole'

/* The 校验 view (M1, spec 2026-09-08 §3): shapes 存取 + 预设、运行、
   横幅/过滤/截断、大本体等待提示。 */

const OID = 'oid-1'
const META: OntologyMeta = {
  id: OID,
  title: 'Mini',
  filename: 'mini.ttl',
  format: 'turtle',
  classCount: 2,
  propertyCount: 0,
  axiomCount: 3,
  instanceCount: 0,
  fileSizeBytes: 100,
  fileHash: 'h',
  revision: 1,
  createdAt: '2026-01-01T00:00:00Z',
  prefixes: { ex: 'http://example.org/' },
}

const RUN_OK = {
  conforms: false,
  focusCount: 2,
  counts: { violation: 1, warning: 1, info: 0 },
  results: [
    {
      severity: 'violation',
      focusIri: 'http://example.org/A',
      focusCurie: 'ex:A',
      path: 'rdfs:label',
      constraint: 'sh:MinCountConstraintComponent',
      message: '每个类应至少有一个 rdfs:label',
      value: null,
    },
    {
      severity: 'warning',
      focusIri: 'http://example.org/B',
      focusCurie: 'ex:B',
      path: null,
      constraint: null,
      message: '类建议带有 rdfs:comment 说明',
      value: null,
    },
  ],
  truncated: false,
  engine: 'pyrudof',
  elapsedMs: 12.5,
  afWarnings: [],
  deprecatedFiltered: 2,
  totalResults: 2,
}

/** The payload the run stub serves this test (tests may swap it). */
let runPayload: unknown = RUN_OK

function env(data: unknown, code = 'OK') {
  return new Response(
    JSON.stringify({ code, message: 'ok', data, hint: null, request_id: 'r' } satisfies Envelope<unknown>),
    { headers: { 'Content-Type': 'application/json' } },
  )
}

let posts: { url: string; body: Record<string, unknown> }[]
let puts: { url: string; body: Record<string, unknown> }[]
let exportsOut: { url: string; body: Record<string, unknown> }[]

function stubFetch() {
  posts = []
  puts = []
  exportsOut = []
  return vi.fn(async (url: string | URL, init?: RequestInit) => {
    const u = String(url)
    const m = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : {}
    if (m === 'POST') {
      if (u.includes('/validation/export')) {
        exportsOut.push({ url: u, body })
        return new Response('csv-bytes', {
          headers: {
            'Content-Type': 'text/csv; charset=utf-8',
            'Content-Disposition': 'attachment; filename="m-validation.csv"',
          },
        })
      }
      posts.push({ url: u, body })
      return env(runPayload)
    }
    if (m === 'PUT') {
      puts.push({ url: u, body })
      return env({ source: body.source, updatedAt: 't', presets: [], afWarnings: [] })
    }
    if (u.endsWith('/validation/shapes'))
      return env({
        source: null,
        updatedAt: null,
        presets: [
          { id: 'obo-integrity', name: 'OBO 风格·完整性', source: '# obo' },
          { id: 'minimal-label', name: '最小检查', source: '# min' },
        ],
      })
    if (u.endsWith('/meta')) return env(META)
    return env({})
  })
}

function draw() {
  vi.stubGlobal('fetch', stubFetch())
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  qc.setQueryData(['ontology', OID], META)
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <ValidationConsole oid={OID} />
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useUiStore.setState({})
  useBrowseStore.setState({ selectedEid: null })
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('ValidationConsole', () => {
  it('loads shapes + presets; preset selection fills the editor (no autosave)', async () => {
    draw()
    await screen.findByLabelText(/shapes/i)
    await screen.findByRole('option', { name: /OBO/ }) // 预设下拉等异步数据
    expect(puts).toHaveLength(0) // 选中预设 ≠ 保存
    await userEvent.selectOptions(screen.getByLabelText(/预设/), 'obo-integrity')
    await userEvent.click(screen.getByRole('button', { name: /运行/ }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].url).toContain(`/api/ontologies/${OID}/validation/run`)
    expect(posts[0].body).toMatchObject({ source: '# obo' })
  })

  it('renders the violation banner, filter chips, and rows; focus click selects', async () => {
    draw()
    await screen.findByLabelText(/shapes/i)
    await userEvent.click(screen.getByRole('button', { name: /运行/ }))
    expect(await screen.findByText(/不符合/)).toBeTruthy()
    expect(screen.getByText('ex:A')).toBeTruthy()
    // 过滤:只看「严重」后 warning 行消失(chip 是 button,role 定位避开表内同词标签)。
    await userEvent.click(screen.getByRole('button', { name: /严重/ }))
    expect(screen.queryByText('ex:B')).toBeNull()
    expect(screen.getByText('ex:A')).toBeTruthy()
    // 焦点点击 → 实体详情(browseStore.selectedEid)。
    await userEvent.click(screen.getByText('ex:A'))
    expect(useBrowseStore.getState().selectedEid).toBe('http://example.org/A')
  })

  it('ignore-deprecated is on by default and the hidden count surfaces', async () => {
    draw()
    await screen.findByLabelText(/shapes/i)
    const box = screen.getByRole('checkbox', { name: /忽略已废弃/ }) as HTMLInputElement
    expect(box.checked).toBe(true)
    await userEvent.click(screen.getByRole('button', { name: /运行/ }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].body).toMatchObject({ includeDeprecated: false })
    expect(await screen.findByText(/已忽略 2 条废弃焦点/)).toBeTruthy()
  })

  it('unchecking ignore-deprecated sends includeDeprecated=true', async () => {
    draw()
    await screen.findByLabelText(/shapes/i)
    await userEvent.click(screen.getByRole('checkbox', { name: /忽略已废弃/ }))
    await userEvent.click(screen.getByRole('button', { name: /运行/ }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].body).toMatchObject({ includeDeprecated: true })
  })

  it('shows the slow-ontology hint for big ontologies', async () => {
    META.classCount = 3000 // > 2000
    draw()
    expect(await screen.findByText(/耐心等待/)).toBeTruthy()
    META.classCount = 2
  })

  it('exports CSV via the dropdown with the current editor + filter', async () => {
    draw()
    await screen.findByLabelText(/shapes/i)
    await screen.findByRole('option', { name: /最小/ }) // 预设异步落地
    await userEvent.selectOptions(screen.getByLabelText(/预设/), 'minimal-label')
    await userEvent.click(screen.getByRole('button', { name: /导出/ }))
    await userEvent.click(screen.getByRole('menuitem', { name: /导出 CSV/ }))
    await waitFor(() => expect(exportsOut).toHaveLength(1))
    expect(exportsOut[0].url).toContain(`/api/ontologies/${OID}/validation/export`)
    expect(exportsOut[0].body).toMatchObject({
      source: '# min',
      includeDeprecated: false,
      format: 'csv',
    })
  })

  it('truncated runs show the true total, not just the rendered count', async () => {
    runPayload = { ...RUN_OK, truncated: true, totalResults: 84823 }
    draw()
    await screen.findByLabelText(/shapes/i)
    await userEvent.click(screen.getByRole('button', { name: /运行/ }))
    expect(await screen.findByText(/共 84,823 条/)).toBeTruthy()
    runPayload = RUN_OK
  })

  it('save PUTs the editor content', async () => {
    draw()
    await screen.findByLabelText(/shapes/i)
    await userEvent.click(screen.getByRole('button', { name: /保存/ }))
    await waitFor(() => expect(puts).toHaveLength(1))
    expect(puts[0].url).toContain(`/api/ontologies/${OID}/validation/shapes`)
  })
})
