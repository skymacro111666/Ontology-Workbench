import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Trash2Icon } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { ApiErr, api } from '../api/client'
import type { OntologyMeta, OntologySummary } from '../api/types'
import { LAST_OID_KEY } from '../auth/AuthContext'
import EmptyState from '../components/EmptyState'
import StatTiles from '../components/StatTiles'
import { useUiStore } from '../stores/uiStore'
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

/** Home (工作台): stat tiles, builtin samples, ontology list cards. */
export default function Home() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const setImportOpen = useUiStore((s) => s.setImportOpen)
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
      toast.success('已删除')
      setDeleteTarget(null)
      void queryClient.invalidateQueries({ queryKey: ['ontologies'] })
    },
    onError: (err) => {
      toast.error(err instanceof ApiErr ? err.message : '操作失败，请稍后重试')
    },
  })

  const sample = useMutation({
    mutationFn: (name: string) => api.post<OntologyMeta>(`/api/samples/${name}`),
    onSuccess: (meta) => {
      void queryClient.invalidateQueries({ queryKey: ['ontologies'] })
      openOntology(meta.id)
    },
    onError: (err) => {
      toast.error(err instanceof ApiErr ? err.message : '载入示例失败，请稍后重试')
    },
  })

  const items: OntologySummary[] = data?.items ?? []
  const totalClasses = items.reduce((sum, o) => sum + o.classCount, 0)
  const totalProperties = items.reduce((sum, o) => sum + o.propertyCount, 0)
  const totalAxioms = items.reduce((sum, o) => sum + o.axiomCount, 0)

  return (
    <div className="mx-auto flex w-full max-w-[1200px] flex-col gap-6 px-6 py-6">
      <h1 className="text-lg font-semibold">我的本体</h1>
      <section className="flex flex-col gap-3" aria-label="本体列表">
        <h2 className="text-sm font-semibold">本体概览</h2>
          <StatTiles
            ontologies={items.length}
            classes={totalClasses}
            properties={totalProperties}
            axioms={totalAxioms}
          />
      </section>

      <section className="flex flex-col gap-3" aria-label="本体列表">
        <h2 className="text-sm font-bold">本体列表</h2>
        {isError ? (
          <div className="border-line flex flex-col items-center gap-3 rounded-card border px-6 py-12 text-center">
            <div className="flex flex-col gap-1">
              <p className="font-medium">列表加载失败</p>
              <p className="text-ink-2 text-sm">无法连接服务器，请确认后端已启动。</p>
            </div>
            <Button size="sm" variant="outline" onClick={() => void refetch()}>
              重试
            </Button>
          </div>
        ) : isPending ? null : items.length === 0 ? (
          <EmptyState
            onLoadSample={() => sample.mutate('pizza')}
            onImport={() => setImportOpen(true)}
          />
        ) : (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {items.map((o) => (
              // mockup list-card: title + fmt pill + actions on the first row,
              // file line under it, counts as tag pills; whole card opens.
              <div
                key={o.id}
                role="button"
                tabIndex={0}
                aria-label={`打开 ${o.title}`}
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
                      打开
                    </Button>
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      aria-label={`删除 ${o.title}`}
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
                    [o.classCount, '类'],
                    [o.propertyCount, '属性'],
                    [o.axiomCount, '公理'],
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
            <AlertDialogTitle>删除「{deleteTarget?.title}」？</AlertDialogTitle>
            <AlertDialogDescription>文件与索引将一并移除，不可恢复。</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
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
              {del.isPending ? '删除中…' : '删除'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
