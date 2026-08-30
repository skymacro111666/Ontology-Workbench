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
