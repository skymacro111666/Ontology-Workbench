import type { Envelope } from './types'
import { useRequestStore } from '../stores/requestStore'

const TOKEN_KEY = 'ow_token'

/** Error thrown when the envelope carries a non-OK code. */
export class ApiErr extends Error {
  readonly code: string
  readonly hint: string | null
  readonly requestId: string

  constructor(code: string, message: string, hint: string | null, requestId: string) {
    super(message)
    this.code = code
    this.hint = hint
    this.requestId = requestId
  }
}

/** Strip the envelope: return data on OK, throw ApiErr otherwise. */
export function unwrap<T>(env: Envelope<T>): T {
  if (env.code !== 'OK') throw new ApiErr(env.code, env.message, env.hint, env.request_id)
  return env.data as T
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const token = localStorage.getItem(TOKEN_KEY)
  const startedAt = performance.now()
  const res = await fetch(url, {
    ...init,
    headers: { ...init?.headers, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  })
  const env = (await res.json()) as Envelope<T>
  if (env.code === 'AUTH_REQUIRED' || env.code === 'TOKEN_EXPIRED') {
    localStorage.removeItem(TOKEN_KEY)
    window.location.href = '/login'
  }
  const data = unwrap(env)
  useRequestStore.getState().set({
    method: init?.method ?? 'GET',
    path: url.replace(/^\/api/, ''),
    ms: performance.now() - startedAt,
    requestId: env.request_id,
  })
  return data
}

/** Envelope-carried file payload (export/file endpoint). */
export interface FilePayload {
  filename: string
  mediaType: string
  content: string
}

/** Fetch an envelope-carried file and trigger the browser download:
 *  blob from the text content, anchor click, then release the URL. */
async function downloadFile(url: string, fallbackName: string): Promise<string> {
  const file = await request<FilePayload>(url)
  const blob = new Blob([file.content], { type: file.mediaType })
  const href = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = href
  a.download = file.filename || fallbackName
  a.click()
  URL.revokeObjectURL(href)
  return file.filename || fallbackName
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
  download: downloadFile,
}
