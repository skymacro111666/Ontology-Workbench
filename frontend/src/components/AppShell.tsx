import { FileTextIcon, KeyRoundIcon, LogOutIcon, Share2Icon } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { LAST_OID_KEY, useAuth } from '../auth/AuthContext'
import { api } from '../api/client'
import { errText } from '../i18n/errText'
import { useUiStore, type BrowseView } from '../stores/uiStore'
import { useTheme } from '../theme/ThemeProvider'
import logoMark from '../assets/logo-mark.png'
import { cn } from '@/lib/utils'
import CommandPalette from './CommandPalette'
import ImportDialog from './ImportDialog'
import OntologySwitcher from './OntologySwitcher'
import PasswordDialog from './PasswordDialog'
import { LangToggle } from './ui/LangToggle'
import { Button } from '@/components/ui/button'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
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
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

const NEXT_THEME = { light: 'dark', dark: 'system', system: 'light' } as const

/** Dropdown file exports: query value → menu label (export/file endpoint). */
const FILE_EXPORTS: [string, string][] = [
  ['turtle', 'Turtle (.ttl)'],
  ['json-ld', 'JSON-LD (.jsonld)'],
  ['rdf-xml', 'RDF/XML (.rdf)'],
]

/** App frame: 48px persistent topbar (logo, nav, switcher, actions) + content.
 *  Nav (mockup): 概览 = home; 工作区 merges browse + the overview canvas. */
export default function AppShell({ children }: { children?: ReactNode }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout } = useAuth()
  const { theme, setTheme } = useTheme()
  const setImportOpen = useUiStore((s) => s.setImportOpen)
  const browseView = useUiStore((s) => s.browseView)
  const setBrowseView = useUiStore((s) => s.setBrowseView)
  const pendingView = useUiStore((s) => s.pendingView)
  const setPendingView = useUiStore((s) => s.setPendingView)
  const [pwdOpen, setPwdOpen] = useState(false)

  /** View switch with a dirty-text guard: route through the dialog. */
  const switchView = (v: BrowseView) => {
    if (browseView === 'text' && v !== 'text' && useUiStore.getState().sourceDirty) {
      setPendingView(v)
      return
    }
    setBrowseView(v)
  }

  /** Open an oid-scoped route; block with a toast until an ontology is chosen. */
  const openLast = (prefix: string) => {
    const last = localStorage.getItem(LAST_OID_KEY)
    if (!last) {
      toast(t('shell.pickOntologyFirst'))
      return
    }
    navigate(`${prefix}/${last}`)
  }

  /** Download the current ontology re-serialized in the given RDF format. */
  const downloadAs = async (format: string) => {
    const last = localStorage.getItem(LAST_OID_KEY)
    if (!last) {
      toast(t('shell.pickOntologyFirst'))
      return
    }
    try {
      const name = await api.download(
        `/api/ontologies/${last}/export/file?format=${format}`,
        'ontology',
      )
      toast.success(t('shell.exportedToast', { name }))
    } catch (err) {
      toast.error(errText(err, t))
    }
  }

  const isWorkspace = location.pathname.startsWith('/browse') || location.pathname.startsWith('/graph')
  const themeLabels = {
    light: t('shell.themeLight'),
    dark: t('shell.themeDark'),
    system: t('shell.themeSystem'),
  }
  const themeCycle = [themeLabels.light, themeLabels.dark, themeLabels.system]
  const themeLabel = themeLabels[theme]

  return (
    <div className="bg-background text-foreground flex h-dvh flex-col">
      <header className="bg-panel border-line flex h-12 shrink-0 items-center gap-5 border-b px-4">
        <div className="flex items-center gap-2">
          {/* Brand mark: the OW letterform cropped from assets/logo.png. */}
          <img src={logoMark} alt="" aria-hidden className="rounded-ctl h-6 w-auto" />
          <span className="text-sm font-bold">Ontology Workbench</span>
        </div>

        <nav className="flex items-center gap-0.5" aria-label={t('shell.mainNav')}>
          <button
            type="button"
            onClick={() => navigate('/')}
            className={cn(
              'rounded-ctl px-3 py-1 text-[13px] font-medium',
              location.pathname === '/'
                ? 'bg-primary-soft text-primary'
                : 'text-ink-2 hover:text-primary',
            )}
          >
            {t('shell.navOverview')}
          </button>
          <button
            type="button"
            onClick={() => openLast('/browse')}
            className={cn(
              'rounded-ctl px-3 py-1 text-[13px] font-medium',
              isWorkspace ? 'bg-primary-soft text-primary' : 'text-ink-2 hover:text-primary',
            )}
          >
            {t('shell.navWorkspace')}
          </button>
        </nav>

        <OntologySwitcher />

        <div className="ml-auto flex items-center gap-2">
          <Button size="sm" onClick={() => setImportOpen(true)}>
            {t('shell.import')}
          </Button>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm">
                {t('shell.exportMenu')}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {/* text-xs per item: the item base class ships text-sm, so a
                  font-size on the content element never reaches the items. */}
              <DropdownMenuItem className="text-xs" onSelect={() => openLast('/export')}>
                {t('shell.exportSite')}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              {FILE_EXPORTS.map(([fmt, label]) => (
                <DropdownMenuItem key={fmt} className="text-xs" onSelect={() => void downloadAs(fmt)}>
                  {label}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>

          {/* Workspace-only content switch: graph canvas vs source text. */}
          {isWorkspace && (
            <ToggleGroup
              type="single"
              variant="outline"
              size="sm"
              value={browseView}
              onValueChange={(v) => {
                if (v) switchView(v as BrowseView)
              }}
            >
              <ToggleGroupItem value="graph">
                <Share2Icon aria-hidden="true" />
                {t('shell.viewGraph')}
              </ToggleGroupItem>
              <ToggleGroupItem value="text">
                <FileTextIcon aria-hidden="true" />
                {t('shell.viewText')}
              </ToggleGroupItem>
            </ToggleGroup>
          )}

          <button
            type="button"
            aria-label={t('shell.themeAria', { current: themeLabel, cycle: themeCycle.join(' / ') })}
            onClick={() => setTheme(NEXT_THEME[theme])}
            className="text-ink-2 hover:bg-panel-2 hover:text-primary rounded-ctl size-8 cursor-pointer"
          >
            ◐
          </button>

          <LangToggle />

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                aria-label={t('shell.userMenu', { name: user?.username ?? t('shell.userFallback') })}
                className="bg-primary-soft text-primary grid size-7 cursor-pointer place-items-center rounded-full text-xs font-semibold"
              >
                {(user?.username ?? t('shell.avatarFallback'))[0].toUpperCase()}
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <div className="text-ink-2 px-2 py-1 text-xs">{user?.username ?? t('shell.userFallback')}</div>
              <DropdownMenuItem className="text-xs" onSelect={() => setPwdOpen(true)}>
                <KeyRoundIcon />
                {t('shell.changePwd')}
              </DropdownMenuItem>
              <DropdownMenuItem
                className="text-xs"
                onSelect={() => {
                  logout()
                  navigate('/login')
                }}
              >
                <LogOutIcon />
                {t('shell.logout')}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>

      {/* children win over Outlet so the test can mount the shell standalone */}
      <main className="min-h-0 flex-1 overflow-y-auto">{children ?? <Outlet />}</main>

      <ImportDialog />
      <CommandPalette />
      <PasswordDialog open={pwdOpen} onClose={() => setPwdOpen(false)} />

      {/* Dirty-text switch guard: save / discard the edits before leaving. */}
      <AlertDialog
        open={pendingView !== null}
        onOpenChange={(o) => {
          if (!o) setPendingView(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('shell.dirtyTitle')}</AlertDialogTitle>
            <AlertDialogDescription>{t('shell.dirtyDesc')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (pendingView) setBrowseView(pendingView)
                setPendingView(null)
              }}
            >
              {t('shell.discardSwitch')}
            </AlertDialogAction>
            <AlertDialogAction
              onClick={() => {
                const target = pendingView
                void (async () => {
                  const saved = (await useUiStore.getState().sourceSaveFn?.()) ?? true
                  setPendingView(null)
                  if (saved && target) setBrowseView(target)
                })()
              }}
            >
              {t('shell.saveSwitch')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
