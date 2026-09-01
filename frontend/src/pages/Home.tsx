import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Trash2Icon } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { ApiErr, api } from '../api/client'
import type { OntologyMeta, OntologySummary } from '../api/types'
import { LAST_OID_KEY } from '../auth/AuthContext'
import { errText } from '../i18n/errText'
import StatTiles from '../components/StatTiles'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${Math.max(1, Math.round(bytes / 1024))} KB`
}

/** ISO timestamp → YYYY-MM-DD, stable across locales and timezones. */
function formatDate(iso: string): string {
  return iso.slice(0, 10)
}

/** Bundled teaching ontologies; names map to backend samples/{name}.ttl. */
const SAMPLES: { name: string; title: string; descKey: string }[] = [
  { name: 'pizza', title: 'Pizza', descKey: 'home.samplesPizza' },
  { name: 'wine', title: 'Wine', descKey: 'home.samplesWine' },
  { name: 'foaf', title: 'FOAF', descKey: 'home.samplesFoaf' },
  { name: 'library', title: 'Library', descKey: 'home.samplesLibrary' },
  { name: 'human-resources-v1', title: 'Human Resources', descKey: 'home.samplesHr' },
]

/** Home (工作台): stat tiles, builtin samples, ontology list cards. */
export default function Home() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [deleteTarget, setDeleteTarget] = useState<OntologySummary | null>(null)

  const { data, isError, isPending, refetch } = useQuery({
    queryKey: ['ontologies'],
    queryFn: () => api.get<{ items: OntologySummary[]; total: number }>('/api/ontologies'),
  })

  const openOntology = (id: string) => {
    localStorage.setItem(LAST_OID_KEY, id)
    navigate(`/browse/${id}`)
  }

  const del = useMutation({
    mutationFn: (id: string) => api.del(`/api/ontologies/${id}`),
    onSuccess: () => {
      toast.success(t('home.deleted'))
      setDeleteTarget(null)
      void queryClient.invalidateQueries({ queryKey: ['ontologies'] })
    },
    onError: (err) => {
      toast.error(errText(err, t))
    },
  })

  const sample = useMutation({
    mutationFn: (name: string) => api.post<OntologyMeta>(`/api/samples/${name}`),
    onSuccess: (meta) => {
      void queryClient.invalidateQueries({ queryKey: ['ontologies'] })
      openOntology(meta.id)
    },
    onError: (err) => {
      toast.error(err instanceof ApiErr ? errText(err, t) : t('home.sampleFailed'))
    },
  })

  const items: OntologySummary[] = data?.items ?? []
  const totalClasses = items.reduce((sum, o) => sum + o.classCount, 0)
  const totalProperties = items.reduce((sum, o) => sum + o.propertyCount, 0)
  const totalAxioms = items.reduce((sum, o) => sum + o.axiomCount, 0)

  /** Sample cards ride the list's tail (user data first); an imported
   *  sample drops its card — the backend loads idempotently per filename,
   *  so the real card simply takes over. */
  const importedNames = new Set(items.map((o) => o.filename))
  const sampleCards = SAMPLES.filter((s) => !importedNames.has(`${s.name}.ttl`)).map(
    (s) => (
      <div
        key={s.name}
        className="border-line bg-panel rounded-card flex flex-col gap-2 border px-4 py-3.5"
      >
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-bold">{s.title}</span>
          <span className="border-line text-ink-3 shrink-0 rounded-full border px-2 py-px font-mono text-[11px]">
            TTL
          </span>
          <span className="bg-primary-soft border-primary-border text-primary shrink-0 rounded-full border px-2 py-px text-[11px] font-bold">
            {t('home.sampleTag')}
          </span>
        </div>
        <p className="text-ink-2 text-sm">{t(s.descKey)}</p>
        <Button
          size="sm"
          variant="outline"
          className="border-line mt-auto self-start"
          disabled={sample.isPending}
          onClick={() => sample.mutate(s.name)}
        >
          {t('home.samplesLoad')}
        </Button>
      </div>
    ),
  )

  return (
    <div className="mx-auto flex w-full max-w-[1200px] flex-col gap-6 px-6 py-6">
      <h1 className="text-lg font-semibold">{t('home.title')}</h1>
      <section className="flex flex-col gap-3" aria-label={t('home.list')}>
        <h2 className="text-sm font-semibold">{t('home.overview')}</h2>
          <StatTiles
            ontologies={items.length}
            classes={totalClasses}
            properties={totalProperties}
            axioms={totalAxioms}
          />
      </section>

      <section className="flex flex-col gap-3" aria-label={t('home.list')}>
        <h2 className="text-sm font-bold">{t('home.list')}</h2>
        {isError ? (
          <div className="border-line flex flex-col items-center gap-3 rounded-card border px-6 py-12 text-center">
            <div className="flex flex-col gap-1">
              <p className="font-medium">{t('home.listFailed')}</p>
              <p className="text-ink-2 text-sm">{t('home.offline')}</p>
            </div>
            <Button size="sm" variant="outline" onClick={() => void refetch()}>
              {t('common.retry')}
            </Button>
          </div>
        ) : isPending ? (
          <div
            role="status"
            aria-label={t('common.loading')}
            className="grid gap-3 md:grid-cols-2 xl:grid-cols-3"
          >
            {/* Six ghost cards mirroring the loaded row shape; bg-line adapts
                to both themes. */}
            {Array.from({ length: 6 }, (_, i) => (
              <div
                key={i}
                className="border-line bg-panel rounded-card flex flex-col gap-2.5 border px-4 py-3.5"
              >
                <div className="bg-line animate-pulse h-4 w-1/2 rounded" />
                <div className="bg-line animate-pulse h-3 w-1/3 rounded" />
                <div className="bg-line animate-pulse h-3 w-2/3 rounded" />
              </div>
            ))}
            <span className="sr-only">{t('home.listLoadingSr')}</span>
          </div>
        ) : items.length === 0 ? (
          // No EmptyState box anymore: the sample cards below keep the list
          // from ever being truly empty, so a one-line hint suffices.
          <div className="flex flex-col gap-3">
            <p className="text-ink-2 text-sm">{t('home.emptyHint')}</p>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{sampleCards}</div>
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {items.map((o) => (
              // mockup list-card: title + fmt pill + actions on the first row,
              // file line under it, counts as tag pills; whole card opens.
              <div
                key={o.id}
                role="button"
                tabIndex={0}
                aria-label={t('home.openAria', { title: o.title })}
                onClick={() => openOntology(o.id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') openOntology(o.id)
                }}
                className="border-line bg-panel hover:border-primary-border rounded-card flex cursor-pointer flex-col gap-2 border px-4 py-3.5 transition-colors hover:shadow-[0_2px_8px_rgba(79,70,229,0.08)]"
              >
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-bold">{o.title}</span>
                  <span className="bg-primary-soft border-primary-border text-primary shrink-0 rounded-full border px-2 py-px font-mono text-[11px] font-bold">
                    {o.format}
                  </span>
                  {o.source === 'sample' && (
                    <span className="bg-primary-soft border-primary-border text-primary shrink-0 rounded-full border px-2 py-px text-[11px] font-bold">
                      {t('home.sampleTag')}
                    </span>
                  )}
                  <span className="border-line ml-auto flex shrink-0 items-center gap-1.5">
                    <Button
                      size="sm"
                      variant="outline"
                      className="border-line"
                      onClick={(e) => {
                        e.stopPropagation()
                        openOntology(o.id)
                      }}
                    >
                      {t('common.open')}
                    </Button>
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      aria-label={t('home.deleteAria', { title: o.title })}
                      onClick={(e) => {
                        e.stopPropagation()
                        setDeleteTarget(o)
                      }}
                    >
                      <Trash2Icon />
                    </Button>
                  </span>
                </div>
                <p className="text-ink-2 truncate text-xs">
                  <span className="font-mono">{o.filename}</span> · {formatSize(o.fileSizeBytes)}{' '}
                  · {formatDate(o.createdAt)}
                </p>
                <div className="flex gap-2">
                  {[
                    [o.classCount, t('home.countClass')],
                    [o.propertyCount, t('home.countProperty')],
                    [o.axiomCount, t('home.countAxiom')],
                  ].map(([count, unit]) => (
                    <span
                      key={unit as string}
                      className="border-line text-ink-2 rounded-full border px-2 py-px text-[11px]"
                    >
                      {count} {unit}
                    </span>
                  ))}
                </div>
              </div>
            ))}
            {sampleCards}
          </div>
        )}
      </section>

      {/* Controlled per-card delete confirm; open only while a target is set. */}
      <AlertDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('home.deleteTitle', { title: deleteTarget?.title ?? '' })}</AlertDialogTitle>
            {/* The filename disambiguates uploads sharing one embedded
             *  dc:title — the title alone has deleted the wrong twin once. */}
            <AlertDialogDescription>
              {t('home.deleteDesc', { filename: deleteTarget?.filename ?? '' })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-white hover:bg-destructive/90 disabled:pointer-events-none disabled:opacity-60"
              disabled={del.isPending}
              onClick={(e) => {
                // Stay open while the delete runs: the dialog is the in-flight
                // feedback (backlog T6②); success closes it in onSuccess.
                e.preventDefault()
                if (deleteTarget) del.mutate(deleteTarget.id)
              }}
            >
              {del.isPending ? t('common.deleting') : t('common.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
