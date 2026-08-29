import type { TFunction } from 'i18next'
import { ApiErr } from '../api/client'

/** Codes whose envelope message carries dynamic detail (entity name, parse
 *  error position) — the mapped text alone would lose it, so append raw. */
const DETAIL_CODES = new Set(['VALIDATION_ERROR', 'PARSE_FAILED'])

/** Single entry point for rendering API errors (spec §错误渲染): mapped code →
 *  localized text; dynamic-detail code → text + raw message; unmapped code →
 *  raw English message; non-ApiErr → the common failure line. */
export function errText(e: unknown, t: TFunction): string {
  if (e instanceof ApiErr) {
    const mapped = t(`err.${e.code}`)
    if (mapped !== `err.${e.code}`) {
      return DETAIL_CODES.has(e.code) ? `${mapped}：${e.message}` : mapped
    }
    return e.message
  }
  return t('common.operationFailed')
}
