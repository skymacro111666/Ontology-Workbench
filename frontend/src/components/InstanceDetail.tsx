import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { InstanceIR } from '../api/types'
import { localName } from '../lib/localName'
import { Chip, Section } from './InspectorPanel'

/** Instance detail (spec §4.2): identity + 类型 chips + 对象/数据属性行。
 *  对象属性行的值是可导航 Chip——实例从详情到详情,无死路。 */
export default function InstanceDetail({ inst, onEdit }: { oid: string; eid: string; inst: InstanceIR; onEdit?: () => void }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(inst.eid)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Fallback for non-secure origins or missing clipboard API
      const textarea = document.createElement('textarea')
      textarea.value = inst.eid
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      const success = document.execCommand('copy')
      document.body.removeChild(textarea)
      if (success) {
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      }
    }
  }
  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto px-4 pt-3.5 pb-3">
      <div className="flex items-center justify-between">
        <span className="microlabel">{t('inspector.detail')}</span>
        <div className="flex items-center gap-2">
          <span className="bg-primary-soft border-primary-border text-primary rounded-full border px-2 py-0.5 text-[10px] font-semibold tracking-wide">
            {t('instance.badge')}
          </span>
          <button
            type="button"
            disabled={!onEdit}
            onClick={onEdit}
            className="border-line text-ink-2 rounded-ctl border px-2 py-0.5 text-[11px] disabled:opacity-50"
          >
            {t('instance.edit')}
          </button>
        </div>
      </div>
      <h3 className="text-primary font-mono text-sm font-bold break-all" title={inst.curie}>
        {localName(inst.curie)}
      </h3>
      <Section label="URI">
        <div className="flex items-start gap-1.5">
          <pre className="text-ink bg-panel-2 border-line rounded-ctl flex-1 border p-1.5 px-2 font-mono text-xs break-all whitespace-pre-wrap">
            {inst.eid}
          </pre>
          <button
            type="button"
            onClick={() => void copy()}
            className="border-line text-ink-2 hover:text-primary rounded-ctl border px-1.5 py-0.5 text-[11px]"
          >
            {copied ? t('instance.copied') : t('instance.copyUri')}
          </button>
        </div>
      </Section>
      {Object.keys(inst.label).length > 0 && (
        <Section label={t('inspector.labels')}>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(inst.label).map(([lang, value]) => (
              <span key={lang} className="border-line text-ink-2 rounded-full border px-2 py-px text-[11px]">
                {Object.keys(inst.label).length > 1 ? `${value} (${lang})` : value}
              </span>
            ))}
          </div>
        </Section>
      )}
      {inst.comment && (
        <Section label={t('inspector.description')}>
          <p className="text-ink-2 text-xs">{inst.comment}</p>
        </Section>
      )}
      <Section label={t('instance.typeSection')} count={inst.classes.length}>
        <div className="flex flex-wrap gap-1.5">
          {inst.classes.map((c) => (
            <Chip key={c.eid} {...c} />
          ))}
        </div>
      </Section>
      <Section label={t('instance.objectProps')} count={inst.objectAssertions.length}>
        <div className="flex flex-col gap-1">
          {inst.objectAssertions.map((a, i) => (
            <div key={`${a.property.eid}-${i}`} className="flex flex-wrap items-baseline gap-1.5 text-xs">
              <span className="text-ink-2 font-mono">{localName(a.property.curie)}</span>
              <span className="text-ink-3">→</span>
              <Chip {...a.object} />
            </div>
          ))}
        </div>
      </Section>
      <Section label={t('instance.dataProps')} count={inst.dataAssertions.length}>
        <div className="flex flex-col gap-1">
          {inst.dataAssertions.map((a, i) => (
            <div key={`${a.property.eid}-${i}`} className="flex flex-wrap items-baseline gap-1.5 text-xs">
              <span className="text-ink-2 font-mono">{localName(a.property.curie)}</span>
              <span className="text-ink-3">=</span>
              <span className="text-ink font-medium">{a.value}</span>
              <span className="text-ink-3 font-mono text-[10px]">{a.datatype.split('#').pop()}</span>
            </div>
          ))}
        </div>
      </Section>
    </div>
  )
}
