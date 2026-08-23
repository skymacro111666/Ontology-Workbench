import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiErr, api, unwrap } from './client'
import { useRequestStore } from '../stores/requestStore'
import type { Envelope } from './types'

describe('unwrap', () => {
  it('returns data on OK', () => {
    const env: Envelope<{ a: number }> = {
      code: 'OK',
      message: 's',
      data: { a: 1 },
      hint: null,
      request_id: 'r',
    }
    expect(unwrap(env)).toEqual({ a: 1 })
  })

  it('throws ApiErr on error code', () => {
    const env: Envelope<never> = {
      code: 'NOT_FOUND',
      message: 'nope',
      data: null,
      hint: 'h',
      request_id: 'r',
    }
    expect(() => unwrap(env)).throws(ApiErr)
  })

  it('throws ApiErr carrying code, hint and request_id', () => {
    const env: Envelope<never> = {
      code: 'DUPLICATE_FILENAME',
      message: 'dup',
      data: null,
      hint: 'rename it',
      request_id: 'rid-1',
    }
    try {
      unwrap(env)
      expect.unreachable('unwrap should have thrown')
    } catch (err) {
      expect(err).toBeInstanceOf(ApiErr)
      const apiErr = err as ApiErr
      expect(apiErr.code).toBe('DUPLICATE_FILENAME')
      expect(apiErr.hint).toBe('rename it')
      expect(apiErr.requestId).toBe('rid-1')
      expect(apiErr.message).toBe('dup')
    }
  })
})

describe('api request auth redirect', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('clears the token and redirects to /login on AUTH_REQUIRED', async () => {
    const store: Record<string, string> = { ow_token: 'stale-token' }
    const fakeWindow = { location: { href: '' } }
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => store[key] ?? null,
      setItem: (key: string, value: string) => {
        store[key] = value
      },
      removeItem: (key: string) => {
        delete store[key]
      },
    })
    vi.stubGlobal('window', fakeWindow)
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            code: 'AUTH_REQUIRED',
            message: 'login required',
            data: null,
            hint: null,
            request_id: 'r2',
          }),
          { status: 401, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )

    await expect(api.get('/api/ontologies')).rejects.toThrow(ApiErr)
    expect(store['ow_token']).toBeUndefined()
    expect(fakeWindow.location.href).toBe('/login')
  })
})

describe('last request tracking', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    useRequestStore.getState().clear()
  })

  it('records method/path/ms/requestId of the latest OK request', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              code: 'OK',
              message: 'm',
              data: {},
              hint: null,
              request_id: 'rid-9',
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
      ),
    )

    await api.post('/api/ping', {})

    const last = useRequestStore.getState().lastRequest
    expect(last?.method).toBe('POST')
    expect(last?.path).toBe('/ping')
    expect(last?.requestId).toBe('rid-9')
    expect(Number.isFinite(last?.ms)).toBe(true)
    expect((last?.ms ?? -1) as number).toBeGreaterThan(0)
  })

  it('does not record failed requests', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              code: 'NOT_FOUND',
              message: 'nope',
              data: null,
              hint: null,
              request_id: 'rid-10',
            }),
            { status: 404, headers: { 'Content-Type': 'application/json' } },
          ),
      ),
    )

    await expect(api.get('/api/none')).rejects.toThrow(ApiErr)
    expect(useRequestStore.getState().lastRequest).toBeNull()
  })
})
