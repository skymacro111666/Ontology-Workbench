import { DownloadIcon, LogOutIcon, MonitorIcon, MoonIcon, SunIcon, UploadIcon, UserIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { Outlet, useNavigate } from 'react-router'
import { toast } from 'sonner'
import { LAST_OID_KEY, useAuth } from '../auth/AuthContext'
import { useUiStore } from '../stores/uiStore'
import { useTheme } from '../theme/ThemeProvider'
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
const THEME_ICON = { light: SunIcon, dark: MoonIcon, system: MonitorIcon } as const
const THEME_LABEL = { light: '浅色', dark: '深色', system: '跟随系统' } as const

/** App frame: 48px persistent topbar (logo, nav, switcher, actions) + content area. */
export default function AppShell({ children }: { children?: ReactNode }) {
  const navigate = useNavigate()
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

  const ThemeIcon = THEME_ICON[theme]

  return (
    <div className="bg-background text-foreground flex h-dvh flex-col">
      <header className="bg-card border-border flex h-12 shrink-0 items-center gap-1 border-b px-3">
        <div className="mr-2 flex items-center gap-2">
          <span
            className="from-primary to-edge-sub text-primary-foreground flex size-7 items-center justify-center rounded-md bg-gradient-to-br text-sm font-semibold"
            aria-hidden
          >
            ◈
          </span>
          <span className="text-sm font-semibold">Ontology Workbench</span>
        </div>

        <nav className="flex items-center gap-1" aria-label="主导航">
          <Button variant="ghost" size="sm" onClick={() => navigate('/')}>
            工作台
          </Button>
          <Button variant="ghost" size="sm" onClick={() => openLast('/browse')}>
            浏览
          </Button>
          <Button variant="ghost" size="sm" onClick={() => openLast('/graph')}>
            总览图
          </Button>
        </nav>

        <OntologySwitcher />

        <div className="ml-auto flex items-center gap-1.5">
          <Button size="sm" onClick={() => setImportOpen(true)}>
            <UploadIcon />
            导入本体
          </Button>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm">
                <DownloadIcon />
                导出
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => openLast('/export')}>导出文档站</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={`切换主题，当前：${THEME_LABEL[theme]}`}
            onClick={() => setTheme(NEXT_THEME[theme])}
          >
            <ThemeIcon />
          </Button>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm">
                <UserIcon />
                {user?.username ?? '用户'}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
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
    </div>
  )
}
