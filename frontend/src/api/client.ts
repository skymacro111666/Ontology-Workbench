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

/** Shared post-response handling: auth bounce, envelope unwrap, request
 *  timing. Used by the fetch path and the XHR upload path alike. */
function settle<T>(env: Envelope<T>, url: string, startedAt: number): T {
  if (env.code === 'AUTH_REQUIRED' || env.code === 'TOKEN_EXPIRED') {
    localStorage.removeItem(TOKEN_KEY)
    window.location.href = '/login'
  }
  const data = unwrap(env)
  useRequestStore.getState().set({
    method: 'POST',
    path: url.replace(/^\/api/, ''),
    ms: performance.now() - startedAt,
    requestId: env.request_id,
  })
  return data
}

/** Multipart upload over XHR — fetch cannot report upload progress, and a
 *  150MB ontology leaves the user blind without it. Envelope semantics
 *  (auth bounce, ApiErr, request timing) match request() via settle(). */
function uploadXHR<T>(
  url: string,
  file: File,
  onProgress?: (loaded: number, total: number) => void,
): Promise<T> {
  const token = localStorage.getItem(TOKEN_KEY)
  const startedAt = performance.now()
  const form = new FormData()
  form.append('file', file)
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', url)
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    if (onProgress) xhr.upload.onprogress = (e) => onProgress(e.loaded, e.total)
    xhr.onerror = () => reject(new TypeError('network error'))
    xhr.onload = () => {
      let env: Envelope<T>
      try {
        env = JSON.parse(xhr.responseText) as Envelope<T>
      } catch {
        reject(new TypeError('invalid response envelope'))
        return
      }
      try {
        resolve(settle(env, url, startedAt))
      } catch (e) {
        reject(e)
      }
    }
    xhr.send(form)
  })
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

/** Authed binary download for endpoints outside the JSON envelope (the
 *  docs-site zip). Errors still arrive as envelopes, so decode those;
 *  success streams a Blob and clicks a transient anchor. Content-
 * -Disposition wins for the filename. */
async function downloadBinary(url: string, fallbackName: string): Promise<string> {
  const token = localStorage.getItem(TOKEN_KEY)
  const res = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!res.ok) {
    const env = (await res.json()) as Envelope<null>
    throw new ApiErr(env.code, env.message, env.hint, env.request_id)
  }
  const blob = await res.blob()
  const cd = res.headers.get('Content-Disposition') ?? ''
  const match = /filename="?([^";]+)"?/.exec(cd)
  const name = match?.[1] ?? fallbackName
  const href = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = href
  a.download = name
  a.click()
  URL.revokeObjectURL(href)
  return name
}

export const api = {
  get: <T>(url: string) => request<T>(url),
  post: <T>(url: string, body?: unknown) =>
    request<T>(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  put: <T>(url: string, body?: unknown) =>
    request<T>(url, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  del: <T>(url: string) => request<T>(url, { method: 'DELETE' }),
  upload: <T>(file: File, onProgress?: (loaded: number, total: number) => void) =>
    uploadXHR<T>('/api/ontologies', file, onProgress),
  download: downloadFile,
  downloadBinary,
}
