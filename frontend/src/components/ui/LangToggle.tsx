import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'

/** Topbar 中/EN toggle — a visible switch beats burying it in a menu (spec). */
export function LangToggle() {
  const { i18n } = useTranslation()
  useEffect(() => {
    document.documentElement.lang = i18n.language
  }, [i18n.language])
  const pick = (lng: 'zh' | 'en') => {
    void i18n.changeLanguage(lng)
    localStorage.setItem('ow_lang', lng)
  }
  const btn = (lng: 'zh' | 'en', label: string) => (
    <button
      type="button"
      aria-pressed={i18n.language === lng}
      onClick={() => pick(lng)}
      className={cn(
        'rounded-ctl px-1.5 py-0.5 text-xs transition-colors',
        i18n.language === lng ? 'bg-primary-soft text-primary font-semibold' : 'text-ink-3 hover:text-ink-1',
      )}
    >
      {label}
    </button>
  )
  return (
    <div className="border-line flex items-center gap-0.5 border-l pl-2" role="group" aria-label="语言 / Language">
      {btn('zh', '中')}
      {btn('en', 'EN')}
    </div>
  )
}
