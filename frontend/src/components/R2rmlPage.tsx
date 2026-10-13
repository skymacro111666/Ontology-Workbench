import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { ApiErr, api } from '../api/client'
import type { R2rmlDoc } from '../api/types'
import R2rmlEditor from './R2rmlEditor'

/** Browse content-area R2RML workbench (P2): 结构 view + 源码 edit tabs.
 *  Both panes stay mounted (hidden, not unmounted) so the editor keeps its
 *  text and dirty state across tab switches. */
export default function R2rmlPage({ oid }: { oid: string }) {
  const { t } = useTranslation()
  const [tab, setTab] = useState<'structure' | 'source'>('structure')
  const doc = useQuery({
    queryKey: ['r2rml', oid],
    queryFn: () => api.get<R2rmlDoc>(`/api/v1/ontologies/${oid}/r2rml`),
    retry: false,
  })
  const missing = doc.error instanceof ApiErr && doc.error.code === 'NOT_FOUND'
  return (
    <div className="flex h-full min-h-0 flex-col gap-2 p-2">
      <ToggleGroup
        type="single"
        variant="outline"
        size="sm"
        value={tab}
        onValueChange={(v) => v && setTab(v as 'structure' | 'source')}
        aria-label={t('r2rml.title')}
      >
        <ToggleGroupItem value="structure">{t('r2rml.tabStructure')}</ToggleGroupItem>
        <ToggleGroupItem value="source">{t('r2rml.tabSource')}</ToggleGroupItem>
      </ToggleGroup>
      {doc.isLoading ? (
        <p className="text-ink-3 text-xs">{t('common.loading')}</p>
      ) : missing ? (
        <p className="text-ink-2 p-8 text-center text-xs">{t('r2rml.noMapping')}</p>
      ) : doc.data ? (
        <>
          <div className={tab === 'structure' ? 'flex min-h-0 flex-1 flex-col' : 'hidden'}>
            <R2rmlStructure doc={doc.data} />
          </div>
          <div className={tab === 'source' ? 'flex min-h-0 flex-1 flex-col' : 'hidden'}>
            <R2rmlEditor oid={oid} doc={doc.data} />
          </div>
        </>
      ) : null}
    </div>
  )
}

/** Structured correspondences (view block moved from R2rmlDialog verbatim). */
function R2rmlStructure({ doc }: { doc: R2rmlDoc }) {
  const { t } = useTranslation()
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-auto">
      {doc.skippedTables.length > 0 && (
        <p className="text-ink-3 text-xs">
          {t('r2rml.skippedBadge')}: {doc.skippedTables.join('、')}
        </p>
      )}
      <div className="border-line overflow-auto rounded-ctl border text-xs">
        {doc.structure.map((m) => (
          <div
            key={m.table}
            className="border-line border-b border-dashed px-2 py-1.5 last:border-0"
          >
            <div className="font-mono">
              {m.table} → {m.className}
            </div>
            {m.columnProps.map((p) => (
              <div key={p.column} className="text-ink-2 font-mono">
                {'  '}
                {p.column} → {p.predicate} ({p.datatype})
              </div>
            ))}
            {m.fkProps.map((p) => (
              <div key={p.predicate} className="text-primary font-mono">
                {'  '}
                {p.predicate}: {p.childColumn} → {p.parentTable}.{p.parentColumn}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}
