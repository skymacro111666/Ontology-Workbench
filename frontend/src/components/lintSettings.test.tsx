import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Envelope, LintReportT } from '../api/types'
import { ThemeProvider } from '../theme/ThemeProvider'
import LintSettingsDialog from './LintSettingsDialog'

/* Rule settings as two tables (启用/名称/级别): builtin checkmark toggles PUT
   the whole config; a custom rule runs itself via 测试 without a prior manual
   save — the button saves first, then POSTs onlyRuleId from the echoed row. */

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
      // Echo back with a stable id so 测试 can address the rule.
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
  it('renders builtins as a table and PUTs the whole config on toggle', async () => {
    draw()
    // Both sections are tables sharing the 启用/名称/级别 headers.
    expect(await screen.findAllByRole('columnheader', { name: '启用' })).toHaveLength(2)
    expect(screen.getAllByRole('columnheader', { name: '名称' })).toHaveLength(2)
    expect(screen.getAllByRole('columnheader', { name: '级别' })).toHaveLength(2)
    // Switch missing-label off via its checkmark and save.
    const toggle = screen.getByRole('button', { name: '缺标签' })
    expect(toggle.getAttribute('aria-pressed')).toBe('true')
    await userEvent.click(toggle)
    expect(toggle.getAttribute('aria-pressed')).toBe('false')
    await userEvent.click(screen.getByRole('button', { name: /保存/ }))
    await waitFor(() => expect(puts).toHaveLength(1))
    expect(puts[0].body.disabled).toContain('missing-label')
    expect(puts[0].url).toBe(`/api/ontologies/${OID}/lint/config`)
  })

  it('creates and tests a custom SPARQL rule without saving first', async () => {
    draw()
    await screen.findByText('缺标签')
    // A fresh config has no custom rules — add a draft row before typing.
    await userEvent.click(screen.getByRole('button', { name: /新建规则/ }))
    await userEvent.type(await screen.findByLabelText(/名称/), '老书')
    const q = 'SELECT ?s WHERE { ?s <http://example.org/year> ?y . FILTER(?y < 1950) }'
    // userEvent.type parses {…} as key descriptors — double the opening
    // braces on input; a lone } is typed literally as-is.
    await userEvent.type(await screen.findByLabelText(/查询/), q.replace(/{/g, '{{'))
    // 测试 activates as soon as the query is non-empty — no manual save.
    await userEvent.click(screen.getByRole('button', { name: /^测试$/ }))
    await waitFor(() => expect(runs).toHaveLength(1))
    expect(puts.length).toBeGreaterThanOrEqual(1) // it saved first
    expect(runs[0]).toEqual({ onlyRuleId: 'rule-0' })
    expect(await screen.findByText(/3 条/)).toBeTruthy()
  })

  it('toggles a custom rule off and PUTs enabled=false', async () => {
    draw()
    await screen.findByText('缺标签')
    await userEvent.click(screen.getByRole('button', { name: /新建规则/ }))
    await userEvent.type(await screen.findByLabelText(/名称/), '老书')
    const toggle = screen.getByRole('button', { name: '老书' })
    expect(toggle.getAttribute('aria-pressed')).toBe('true')
    await userEvent.click(toggle)
    await userEvent.click(screen.getByRole('button', { name: /保存/ }))
    await waitFor(() => expect(puts).toHaveLength(1))
    expect(puts[0].body.custom[0]).toMatchObject({ name: '老书', enabled: false })
  })
})
