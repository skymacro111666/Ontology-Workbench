import type { CSSProperties } from 'react'
import { Toaster as Sonner, type ToasterProps } from 'sonner'
import { useTheme } from '../../theme/ThemeProvider'

// Vendored from shadcn/ui; next-themes replaced by the app's ThemeProvider,
// which owns theme resolution — sonner only receives the resolved value, so
// an explicit app choice beats the OS preference (backlog Minor#3).
const Toaster = ({ ...props }: ToasterProps) => {
  const { resolved } = useTheme()
  return (
    <Sonner
      theme={resolved}
      className="toaster group"
      style={
        {
          '--normal-bg': 'var(--popover)',
          '--normal-text': 'var(--popover-foreground)',
          '--normal-border': 'var(--border)',
        } as CSSProperties
      }
      {...props}
    />
  )
}

export { Toaster }
