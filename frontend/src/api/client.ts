import type { Envelope } from './types'

const TOKEN_KEY = 'ow_token'

/** Error thrown when the envelope carries a non-OK code. */
export class ApiErr extends Error {
  constructor(
    public code: string,
    message: string,
    public hint: string | null,
    public requestId: string,
  ) {
    super(message)
  }
}

/** Strip the envelope: return data on OK, throw ApiErr otherwise. */
export function unwrap<T>(env: Envelope<T>): T {
  if (env.code !== 'OK') throw new ApiErr(env.code, env.message, env.hint, env.request_id)
  return env.data as T
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const token = localStorage.getItem(TOKEN_KEY)
  const res = await fetch(url, {
    ...init,
    headers: { ...init?.headers, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  })
  const env = (await res.json()) as Envelope<T>
  if (env.code === 'AUTH_REQUIRED' || env.code === 'TOKEN_EXPIRED') {
    localStorage.removeItem(TOKEN_KEY)
    window.location.href = '/login'
  }
  return unwrap(env)
}

export const api = {
  get: <T>(url: string) => request<T>(url),
  post: <T>(url: string, body?: unknown) =>
    request<T>(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  del: <T>(url: string) => request<T>(url, { method: 'DELETE' }),
  upload: async <T>(file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<T>('/api/ontologies', { method: 'POST', body: form })
  },
}
