import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { CheckIcon, MessageSquareIcon, PencilIcon, PlusIcon, Trash2Icon, XIcon } from 'lucide-react'
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'
import type { ChatSessionSummary } from '../../api/types'

type T = (key: string, opts?: Record<string, unknown>) => string

/** zh relative time for session rows — 分钟/小时/天 is enough for a chat list. */
export function timeAgoLabel(t: T, iso: string): string {
  const mins = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 60_000))
  if (mins < 1) return t('chatPanel.justNow')
  if (mins < 60) return t('chatPanel.minAgo', { n: mins })
  if (mins < 24 * 60) return t('chatPanel.hourAgo', { n: Math.floor(mins / 60) })
  return t('chatPanel.dayAgo', { n: Math.floor(mins / (24 * 60)) })
}

/** Header session segment (approved mockup 会话管理): history button opening
 *  the session list popover — ＋新对话, switch rows, hover rename/delete.
 *  Data operations stay in the drawer; this menu is presentational plus its
 *  inline rename draft and delete-confirm state. */
export default function SessionMenu({
  sessions,
  activeId,
  onSwitch,
  onNew,
  onRename,
  onDelete,
}: {
  sessions: ChatSessionSummary[]
  activeId: string | null
  onSwitch: (s: ChatSessionSummary) => void
  onNew: () => void
  onRename: (s: ChatSessionSummary, title: string) => Promise<void>
  onDelete: (s: ChatSessionSummary) => Promise<void>
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [renaming, setRenaming] = useState<ChatSessionSummary | null>(null)
  const [draft, setDraft] = useState('')
  const [confirming, setConfirming] = useState<ChatSessionSummary | null>(null)
  const [busy, setBusy] = useState(false)

  const startRename = (s: ChatSessionSummary) => {
    setRenaming(s)
    setDraft(s.title ?? '')
  }
  const commitRename = async () => {
    if (!renaming || !draft.trim() || busy) return
    setBusy(true)
    try {
      await onRename(renaming, draft.trim())
      setRenaming(null)
    } finally {
      setBusy(false)
    }
  }
  const confirmDelete = async () => {
    if (!confirming) return
    const target = confirming
    setConfirming(null)
    setBusy(true)
    try {
      await onDelete(target)
    } finally {
      setBusy(false)
    }
  }

  const iconBtn =
    'border-line text-ink-2 hover:bg-panel-2 hover:text-ink inline-flex items-center gap-1 rounded-ctl border bg-transparent p-1'
  const actBtn =
    'border-line text-ink-3 hover:bg-panel-2 hover:text-ink inline-flex items-center rounded-ctl border bg-transparent p-0.5'

  return (
    <>
      <DropdownMenu open={open} onOpenChange={setOpen}>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            aria-label={t('chatPanel.sessionsAria')}
            title={t('chatPanel.sessionsAria')}
            className={iconBtn}
          >
            <MessageSquareIcon aria-hidden="true" className="size-3.5" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-72">
          <div className="border-line flex items-center justify-between border-b border-dashed px-2.5 py-1.5">
            <b className="text-ink-2 text-[11px] font-semibold">{t('chatPanel.sessions')}</b>
            <button
              type="button"
              onClick={() => {
                onNew()
                setOpen(false)
              }}
              className={iconBtn}
            >
              <PlusIcon aria-hidden="true" className="size-3" />
              {t('chatPanel.newChat')}
            </button>
          </div>
          {sessions.length === 0 && (
            <p className="text-ink-3 px-2.5 py-3 text-center text-[11px]">{t('chatPanel.noSessions')}</p>
          )}
          {sessions.map((s) =>
            renaming?.id === s.id ? (
              <div key={s.id} className="border-line flex items-center gap-1.5 border-b border-dashed px-2.5 py-1.5 last:border-b-0">
                <input
                  value={draft}
                  autoFocus
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.nativeEvent.isComposing) return // IME confirm Enter
                    if (e.key === 'Enter') void commitRename()
                    else if (e.key === 'Escape') setRenaming(null)
                  }}
                  className="border-primary bg-panel text-ink min-w-0 flex-1 rounded-ctl border px-1.5 py-1 text-xs outline-none"
                />
                <button
                  type="button"
                  aria-label={t('chatPanel.renameOk')}
                  disabled={busy}
                  onClick={() => void commitRename()}
                  className="border-success/40 text-success inline-flex items-center rounded-ctl border bg-transparent p-1"
                >
                  <CheckIcon aria-hidden="true" className="size-3" />
                </button>
                <button
                  type="button"
                  aria-label={t('common.cancel')}
                  onClick={() => setRenaming(null)}
                  className={actBtn}
                >
                  <XIcon aria-hidden="true" className="size-3" />
                </button>
              </div>
            ) : (
              <DropdownMenuItem
                key={s.id}
                onSelect={() => onSwitch(s)}
                className={cn('flex items-center gap-2 px-2.5 py-2', s.id === activeId && 'bg-primary-soft')}
              >
                <span className="min-w-0 flex-1">
                  <b className="block truncate text-[12px] font-semibold">{s.title ?? t('chatPanel.untitled')}</b>
                  <small className="text-ink-3 block text-[10px]">
                    {t('chatPanel.rowMeta', { time: timeAgoLabel(t, s.updatedAt), n: s.messageCount })}
                  </small>
                </span>
                <span className="flex shrink-0 gap-1">
                  <button
                    type="button"
                    aria-label={t('chatPanel.rename')}
                    title={t('chatPanel.rename')}
                    onClick={(e) => {
                      e.stopPropagation()
                      startRename(s)
                    }}
                    className={actBtn}
                  >
                    <PencilIcon aria-hidden="true" className="size-3" />
                  </button>
                  <button
                    type="button"
                    aria-label={t('common.delete')}
                    title={t('common.delete')}
                    onClick={(e) => {
                      e.stopPropagation()
                      setOpen(false)
                      setConfirming(s)
                    }}
                    className={actBtn}
                  >
                    <Trash2Icon aria-hidden="true" className="size-3" />
                  </button>
                </span>
              </DropdownMenuItem>
            ),
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      {/* Delete confirm — outside the menu so closing it (to host the dialog)
       * does not unmount the dialog itself. */}
      <AlertDialog open={!!confirming} onOpenChange={(o) => !o && setConfirming(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('chatPanel.deleteTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('chatPanel.deleteBody', { title: confirming?.title ?? '' })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={() => void confirmDelete()}>{t('chatPanel.deleteConfirm')}</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
