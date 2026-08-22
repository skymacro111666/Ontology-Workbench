import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

type Choice = 'light' | 'dark' | 'system'
const KEY = 'ow_theme'

interface ThemeCtx {
  theme: Choice
  resolved: 'light' | 'dark'
  setTheme: (t: Choice) => void
}

const Ctx = createContext<ThemeCtx | null>(null)

/** Tri-state theme (spec D8): light/dark/system, remembered in localStorage. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Choice>(
    () => (localStorage.getItem(KEY) as Choice) || 'system',
  )
  const systemDark = usePrefersDark()
  const resolved: 'light' | 'dark' =
    theme === 'system' ? (systemDark ? 'dark' : 'light') : theme

  useEffect(() => {
    document.documentElement.classList.toggle('dark', resolved === 'dark')
  }, [resolved])

  const setTheme = (t: Choice) => {
    localStorage.setItem(KEY, t)
    setThemeState(t)
  }

  return <Ctx.Provider value={{ theme, resolved, setTheme }}>{children}</Ctx.Provider>
}

export function useTheme(): ThemeCtx {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider')
  return ctx
}

function usePrefersDark(): boolean {
  const [dark, setDark] = useState(
    () => window.matchMedia('(prefers-color-scheme: dark)').matches,
  )
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const on = (e: MediaQueryListEvent) => setDark(e.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return dark
}
