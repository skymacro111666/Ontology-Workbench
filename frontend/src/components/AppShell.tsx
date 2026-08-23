import { LogOutIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router'
import { toast } from 'sonner'
import { LAST_OID_KEY, useAuth } from '../auth/AuthContext'
import { useUiStore } from '../stores/uiStore'
import { useTheme } from '../theme/ThemeProvider'
import { cn } from '@/lib/utils'
import CommandPalette from './CommandPalette'
import ImportDialog from './ImportDialog'
import OntologySwitcher from './OntologySwitcher'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

const NEXT_THEME = { light: 'dark', dark: 'system', system: 'light' } as const
const THEME_LABEL = { light: '浅色', dark: '深色', system: '跟随系统' } as const

/** App frame: 48px persistent topbar (logo, nav, switcher, actions) + content.
 *  Nav (mockup): 概览 = home; 工作区 merges browse + the overview canvas. */
export default function AppShell({ children }: { children?: ReactNode }) {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout } = useAuth()
  const { theme, setTheme } = useTheme()
  const setImportOpen = useUiStore((s) => s.setImportOpen)

  /** Open an oid-scoped route; block with a toast until an ontology is chosen. */
  const openLast = (prefix: string) => {
    const last = localStorage.getItem(LAST_OID_KEY)
    if (!last) {
      toast('先选择一个本体')
      return
    }
    navigate(`${prefix}/${last}`)
  }

  const isWorkspace = location.pathname.startsWith('/browse') || location.pathname.startsWith('/graph')
  const themeCycle = ['浅色', '深色', '跟随系统'] as const
  const themeLabel = THEME_LABEL[theme]

  return (
    <div className="bg-background text-foreground flex h-dvh flex-col">
      <header className="bg-panel border-line flex h-12 shrink-0 items-center gap-5 border-b px-4">
        <div className="flex items-center gap-2">
          <span
            className="from-primary to-edge-sub text-primary-foreground flex size-6 items-center justify-center rounded-md bg-gradient-to-br text-xs font-semibold"
            aria-hidden
          >
            ◈
          </span>
          <span className="text-sm font-bold">Ontology Workbench</span>
        </div>

        <nav className="flex items-center gap-0.5" aria-label="主导航">
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
            概览
          </button>
          <button
            type="button"
            onClick={() => openLast('/browse')}
            className={cn(
              'rounded-ctl px-3 py-1 text-[13px] font-medium',
              isWorkspace ? 'bg-primary-soft text-primary' : 'text-ink-2 hover:text-primary',
            )}
          >
            工作区
          </button>
        </nav>

        <OntologySwitcher />

        <div className="ml-auto flex items-center gap-2">
          <Button size="sm" onClick={() => setImportOpen(true)}>
            ＋ 导入本体
          </Button>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm">
                导出 ▾
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => openLast('/export')}>导出文档站</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          <button
            type="button"
            aria-label={`切换主题，当前：${themeLabel}（依次切换${themeCycle.join(' / ')}）`}
            onClick={() => setTheme(NEXT_THEME[theme])}
            className="text-ink-2 hover:bg-panel-2 hover:text-primary rounded-ctl size-8 cursor-pointer"
          >
            ◐
          </button>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                aria-label={`${user?.username ?? '用户'} 菜单`}
                className="bg-primary-soft text-primary grid size-7 cursor-pointer place-items-center rounded-full text-xs font-semibold"
              >
                {(user?.username ?? '用')[0].toUpperCase()}
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <div className="text-ink-2 px-2 py-1 text-xs">{user?.username ?? '用户'}</div>
              <DropdownMenuItem
                onSelect={() => {
                  logout()
                  navigate('/login')
                }}
              >
                <LogOutIcon />
                退出登录
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>

      {/* children win over Outlet so the test can mount the shell standalone */}
      <main className="min-h-0 flex-1 overflow-y-auto">{children ?? <Outlet />}</main>

      <ImportDialog />
      <CommandPalette />
    </div>
  )
}
