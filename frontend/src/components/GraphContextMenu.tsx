import { useEffect, useRef } from 'react'

/** One row of the canvas context menu. */
export interface MenuItem {
  key: string
  label: string
  danger?: boolean
  onSelect: () => void
}

/** Self-drawn absolute-positioned menu for G6 right-clicks (blank canvas
 *  or node). Radix ContextMenu wraps a DOM trigger, which the canvas can't
 *  provide — this rides plain coordinates instead, styled with project
 *  tokens, closing on Esc / outside pointer / scroll. */
export default function GraphContextMenu({
  x,
  y,
  items,
  onClose,
}: {
  x: number
  y: number
  items: MenuItem[]
  onClose: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    const onDown = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose()
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('pointerdown', onDown, true)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('pointerdown', onDown, true)
    }
  }, [onClose])

  return (
    <div
      ref={ref}
      role="menu"
      style={{ left: x, top: y }}
      className="border-line bg-panel text-ink rounded-ctl absolute z-20 flex min-w-40 flex-col border p-1 shadow-md"
      onContextMenu={(e) => e.preventDefault()}
    >
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          role="menuitem"
          onClick={() => {
            onClose()
            item.onSelect()
          }}
          className={
            'rounded-ctl cursor-pointer px-3 py-1.5 text-left text-[13px] ' +
            (item.danger
              ? 'text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/40'
              : 'text-ink-2 hover:bg-panel-2 hover:text-primary')
          }
        >
          {item.label}
        </button>
      ))}
    </div>
  )
}
