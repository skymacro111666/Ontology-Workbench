import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Envelope } from '../api/types'
import { useBrowseStore } from '../stores/browseStore'
import { ThemeProvider } from '../theme/ThemeProvider'
import InspectorPanel from './InspectorPanel'

const OID = 'oid-1'
const SF = 'http://example.org/library#ScienceFiction'
const TB = 'http://example.org/library#ThreeBody'
const LCX = 'http://example.org/library#LiuCixin'

const INSTANCE = {
  eid: TB,
  curie: 'lib:ThreeBody',
  kind: 'instance',
  label: { en: 'ThreeBody' },
  comment: null,
  classes: [{ eid: SF, curie: 'lib:ScienceFiction', label: {} }],
  objectAssertions: [
    {
      property: {
        eid: 'http://example.org/library#hasCreator',
        curie: 'lib:hasCreator',
        label: {},
        ptype: 'ObjectProperty',
      },
      object: { eid: LCX, curie: 'lib:LiuCixin', label: { en: '刘慈ixin' } },
    },
  ],
  dataAssertions: [
    {
      property: {
        eid: 'http://example.org/library#publicationYear',
        curie: 'lib:publicationYear',
        label: {},
        ptype: 'DatatypeProperty',
      },
      value: '2008',
      datatype: 'http://www.w3.org/2001/XMLSchema#integer',
    },
  ],
}

function env(data: unknown, code = 'OK') {
  return new Response(
    JSON.stringify({ code, message: 'ok', data, hint: null, request_id: 'r' } satisfies Envelope<unknown>),
    { headers: { 'Content-Type': 'application/json' } },
  )
}

function draw() {
  const fetchMock = vi.fn(async (url: string | URL) => {
    const u = String(url)
    if (u.includes('/entities/')) return env(INSTANCE)
    return env({})
  })
  vi.stubGlobal('fetch', fetchMock)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <InspectorPanel oid={OID} eid={TB} />
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useBrowseStore.setState({ selectedEid: null, revealEid: null })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('InstanceDetail view', () => {
  it('renders types/object rows/data rows; object value navigates on click', async () => {
    draw()
    expect(await screen.findAllByText('ThreeBody')).toHaveLength(2) // h3 + label
    expect(screen.getByRole('button', { name: 'ScienceFiction' })).toBeTruthy() // 类型 chip
    expect(screen.getByRole('button', { name: '刘慈ixin' })).toBeTruthy() // 对象属性值
    expect(screen.getByText('2008')).toBeTruthy() // 数据字面量
    await userEvent.click(screen.getByRole('button', { name: '刘慈ixin' }))
    expect(useBrowseStore.getState().selectedEid).toBe(LCX) // 值可导航,无死路
  })

  it('copies the URI', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    draw()
    await userEvent.click(await screen.findByRole('button', { name: /复制/ }))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(TB))
  })
})

describe('InstanceDetail edit mode', () => {
  const SCHEMA = [
    { eid: 'http://example.org/library#hasCreator', curie: 'lib:hasCreator', label: {}, ptype: 'ObjectProperty', inherited: false, via: null, target: { kind: 'class', curie: 'lib:Person', eid: 'http://example.org/library#Person', declared: true } },
    { eid: 'http://example.org/library#publicationYear', curie: 'lib:publicationYear', label: {}, ptype: 'DatatypeProperty', inherited: false, via: null, target: { kind: 'datatype', curie: 'xsd:integer', eid: null, declared: null } },
  ]
  const SEARCH_HITS = [
    { eid: LCX, curie: 'lib:LiuCixin', label: { en: '刘慈ixin' }, type: 'Instance', matchedField: 'label' },
  ]
  // Edit-mode rows seed from the instance's assertions; dropping the object
  // assertion keeps the seeded row count at one (deletable → assertions []).
  const EDIT_INSTANCE = { ...INSTANCE, objectAssertions: [] }
  let put: { url: string; body: Record<string, unknown> }[] = []

  function drawEdit(inst: unknown = EDIT_INSTANCE) {
    put = []
    const fetchMock = vi.fn(async (url: string | URL, init?: RequestInit) => {
      const u = String(url)
      const method = init?.method ?? 'GET'
      if (method === 'PUT') {
        put.push({ url: u, body: JSON.parse(String(init?.body)) as Record<string, unknown> })
        return env({ meta: {}, entity: { eid: TB, curie: 'lib:ThreeBody', type: 'Instance' } })
      }
      if (u.includes('/assertion-schema')) return env(SCHEMA)
      if (u.includes('/search')) return env(SEARCH_HITS)
      if (u.includes('/entities/')) return env(inst)
      if (u.endsWith('/meta')) return env({ fileHash: 'hash-2' })
      if (u.includes('/overview')) return env({ nodes: [{ id: SF, curie: 'lib:ScienceFiction', label: {}, kind: 'class' }], edges: [] })
      return env({})
    })
    vi.stubGlobal('fetch', fetchMock)
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return render(
      <QueryClientProvider client={qc}>
        <ThemeProvider><InspectorPanel oid={OID} eid={TB} /></ThemeProvider>
      </QueryClientProvider>,
    )
  }

  /** Save stays disabled until meta (baseFileHash) resolves — the tests wait
   *  for it just like a user would. */
  async function awaitSaveEnabled() {
    await waitFor(() =>
      expect((screen.getByRole('button', { name: /保存/ }) as HTMLButtonElement).disabled).toBe(false),
    )
  }

  it('batch-saves comment/classes/assertions in one PUT', async () => {
    drawEdit()
    await screen.findAllByText('ThreeBody')
    await userEvent.click(screen.getByRole('button', { name: /编辑/ }))
    // 新属性行:选 hasCreator,搜索选实例
    await userEvent.click(await screen.findByRole('button', { name: /添加属性/ }))
    await userEvent.click(await screen.findByRole('button', { name: /hasCreator/ }))
    const search = await screen.findByPlaceholderText(/搜索实例/)
    await userEvent.type(search, '刘慈')
    await userEvent.click(await screen.findByRole('button', { name: '刘慈ixin' }))
    await awaitSaveEnabled()
    await userEvent.click(screen.getByRole('button', { name: /保存/ }))
    await waitFor(() => expect(put).toHaveLength(1))
    expect(put[0].url).toContain(`/instances/`)
    expect(put[0].body.baseFileHash).toBe('hash-2')
    // 全量替换:未动的 publicationYear 原行 + 新加的 hasCreator 行
    expect(put[0].body.assertions).toEqual([
      expect.objectContaining({ property: 'http://example.org/library#publicationYear', kind: 'data', value: '2008', datatype: 'http://www.w3.org/2001/XMLSchema#integer' }),
      expect.objectContaining({ property: 'http://example.org/library#hasCreator', kind: 'object', value: LCX }),
    ])
  })

  it('remove buttons drop rows before save', async () => {
    drawEdit()
    await screen.findAllByText('ThreeBody')
    await userEvent.click(screen.getByRole('button', { name: /编辑/ }))
    const del = await screen.findAllByRole('button', { name: /删除行|×/ })
    await userEvent.click(del[0])
    await awaitSaveEnabled()
    await userEvent.click(screen.getByRole('button', { name: /保存/ }))
    await waitFor(() => expect(put).toHaveLength(1))
    expect(put[0].body.assertions).toEqual([])
  })

  it('same property can gain a second row (multi-value)', async () => {
    drawEdit(INSTANCE) // 已有一条 hasCreator 行
    await screen.findAllByText('ThreeBody')
    await userEvent.click(screen.getByRole('button', { name: /编辑/ }))
    await userEvent.click(await screen.findByRole('button', { name: /添加属性/ }))
    // hasCreator 已在行里,仍可再加一条(spec §0 同属性可多行)
    await userEvent.click(await screen.findByRole('button', { name: /hasCreator/ }))
    const search = await screen.findByPlaceholderText(/搜索实例/)
    await userEvent.type(search, '刘慈')
    await userEvent.click(await screen.findByRole('button', { name: '刘慈ixin' }))
    await awaitSaveEnabled()
    await userEvent.click(screen.getByRole('button', { name: /保存/ }))
    await waitFor(() => expect(put).toHaveLength(1))
    const has = (put[0].body.assertions as { property: string }[]).filter(
      (a) => a.property === 'http://example.org/library#hasCreator',
    )
    expect(has).toHaveLength(2) // 种子行 + 新行
  })

  it('rows left without a value are dropped from the save', async () => {
    drawEdit()
    await screen.findAllByText('ThreeBody')
    await userEvent.click(screen.getByRole('button', { name: /编辑/ }))
    await userEvent.click(await screen.findByRole('button', { name: /添加属性/ }))
    await userEvent.click(await screen.findByRole('button', { name: /hasCreator/ })) // 不选值
    await awaitSaveEnabled()
    await userEvent.click(screen.getByRole('button', { name: /保存/ }))
    await waitFor(() => expect(put).toHaveLength(1))
    expect(put[0].body.assertions).toEqual([
      expect.objectContaining({ property: 'http://example.org/library#publicationYear', kind: 'data', value: '2008' }),
    ])
  })

  it('edit state resets when switching to another (cached) instance', async () => {
    const OB = 'http://example.org/library#OtherBook'
    const B_INSTANCE = { ...INSTANCE, eid: OB, curie: 'lib:OtherBook', label: {}, objectAssertions: [], dataAssertions: [] }
    const fetchMock = vi.fn(async (url: string | URL, init?: RequestInit) => {
      const u = String(url)
      if ((init?.method ?? 'GET') === 'PUT') return env({ meta: {}, entity: {} })
      if (u.includes('/assertion-schema')) return env(SCHEMA)
      if (u.includes('/search')) return env(SEARCH_HITS)
      if (u.includes(encodeURIComponent(OB))) return env(B_INSTANCE)
      if (u.includes('/entities/')) return env(INSTANCE)
      if (u.endsWith('/meta')) return env({ fileHash: 'hash-2' })
      if (u.includes('/overview')) return env({ nodes: [{ id: SF, curie: 'lib:ScienceFiction', label: {}, kind: 'class' }], edges: [] })
      return env({})
    })
    vi.stubGlobal('fetch', fetchMock)
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const ui = (eid: string) => (
      <QueryClientProvider client={qc}>
        <ThemeProvider><InspectorPanel oid={OID} eid={eid} /></ThemeProvider>
      </QueryClientProvider>
    )
    const view = render(ui(TB))
    await screen.findAllByText('ThreeBody')
    view.rerender(ui(OB)) // 先访问 B,让 react-query 缓存它
    await screen.findByText('OtherBook')
    view.rerender(ui(TB))
    await screen.findAllByText('ThreeBody')
    await userEvent.click(screen.getByRole('button', { name: /编辑/ }))
    expect(await screen.findByRole('button', { name: /添加属性/ })).toBeTruthy()
    // 缓存的 B 同步返回、没有 undefined 间隙——没有 key 就会带着 A 的草稿停在编辑态
    view.rerender(ui(OB))
    expect(await screen.findByText('OtherBook')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /添加属性/ })).toBeNull() // 编辑态 UI 消失
    expect(screen.getByRole('button', { name: /编辑/ })).toBeTruthy() // 回到查看态
  })
})
