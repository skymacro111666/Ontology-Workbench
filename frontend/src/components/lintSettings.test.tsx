import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Envelope, LintReportT } from '../api/types'
import { ThemeProvider } from '../theme/ThemeProvider'
import LintSettingsDialog from './LintSettingsDialog'

/* Rule settings: builtin toggles PUT the whole config; custom SPARQL rules
   save then run themselves via onlyRuleId (the「测试」button). */

const OID = 'oid-1'

interface ConfigShape {
  disabled: string[]
  custom: { id: string; name: string; severity: string; sparql: string; enabled: boolean }[]
}

let config: ConfigShape = { disabled: [], custom: [] }
let puts: { url: string; body: ConfigShape }[]
let runs: Record<string, unknown>[]

const RUN_REPORT: LintReportT = {
  fileHash: 'h1',
  durationMs: 5.5,
  counts: { error: 0, warning: 0, info: 3 },
  results: [
    {
      ruleId: '',
      name: '老书',
      severity: 'info',
      durationMs: 4.1,
      findings: Array.from({ length: 3 }, (_, i) => ({
        ruleId: '',
        severity: 'info',
        subject: `http://example.org/b${i}`,
        subjectCurie: `lib:b${i}`,
        params: {},
      })),
      total: 3,
      truncated: false,
      error: null,
    },
  ],
}

function env(data: unknown) {
  return new Response(
    JSON.stringify({ code: 'OK', message: 'ok', data, hint: null, request_id: 'r' } satisfies Envelope<unknown>),
    { headers: { 'Content-Type': 'application/json' } },
  )
}

function stubFetch() {
  puts = []
  runs = []
  return vi.fn(async (url: string | URL, init?: RequestInit) => {
    const u = String(url)
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : {}
    if (u.endsWith('/lint/config') && method === 'PUT') {
      puts.push({ url: u, body })
      // Echo back with a stable id so「测试」can address the rule.
      const echo = {
        disabled: body.disabled,
        custom: body.custom.map((c: ConfigShape['custom'][number], i: number) => ({
          id: `rule-${i}`,
          name: c.name,
          severity: c.severity,
          sparql: c.sparql,
          enabled: c.enabled,
        })),
      }
      config = echo as ConfigShape
      return env(echo)
    }
    if (u.endsWith('/lint/config')) return env(config)
    if (u.endsWith('/lint/run')) {
      runs.push(body)
      return env(RUN_REPORT)
    }
    return env({})
  })
}

function draw() {
  vi.stubGlobal('fetch', stubFetch())
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <LintSettingsDialog oid={OID} open onOpenChange={() => {}} />
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  config = { disabled: [], custom: [] }
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('LintSettingsDialog', () => {
  it('toggles a builtin rule and PUTs the whole config', async () => {
    draw()
    // The builtin list renders all nine rules with their localized names.
    expect(await screen.findByText('缺标签')).toBeTruthy()
    expect(screen.getByText('不相交父类')).toBeTruthy()
    // Switch missing-label off, save, and the PUT carries the whole set.
    await userEvent.click(screen.getByRole('button', { name: /缺标签/ }))
    await userEvent.click(screen.getByRole('button', { name: /保存/ }))
    await waitFor(() => expect(puts).toHaveLength(1))
    expect(puts[0].body.disabled).toContain('missing-label')
    expect(puts[0].url).toBe(`/api/ontologies/${OID}/lint/config`)
  })

  it('creates and tests a custom SPARQL rule', async () => {
    draw()
    await screen.findByText('缺标签')
    // A fresh config has no custom rules — add a draft row before typing.
    await userEvent.click(screen.getByRole('button', { name: /新建规则/ }))
    await userEvent.type(await screen.findByLabelText(/名称/), '老书')
    const q = 'SELECT ?s WHERE { ?s <http://example.org/year> ?y . FILTER(?y < 1950) }'
    // userEvent.type parses {…} as key descriptors — double the opening
    // braces on input; a lone } is typed literally as-is.
    await userEvent.type(await screen.findByLabelText(/查询/), q.replace(/{/g, '{{'))
    await userEvent.click(screen.getByRole('button', { name: /保存/ }))
    await waitFor(() => expect(puts).toHaveLength(1))
    expect(puts[0].body.custom[0]).toMatchObject({ name: '老书', sparql: q, severity: 'info' })
    // 测试 saves first, then runs only that rule by its echoed id.
    await userEvent.click(screen.getByRole('button', { name: /^测试$/ }))
    await waitFor(() => expect(runs).toHaveLength(1))
    expect(runs[0]).toEqual({ onlyRuleId: 'rule-0' })
    expect(await screen.findByText(/3 条/)).toBeTruthy()
  })
})
