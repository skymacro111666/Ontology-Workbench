import { useEffect, useRef, useState } from 'react'

/**
 * Observe the caller's container height so virtual lists (AntD Tree `height`)
 * can fill the sidebar. Falls back to a sane default where ResizeObserver is
 * missing (jsdom).
 */
export function useContainerHeight<T extends HTMLElement>(fallback = 400) {
  const ref = useRef<T | null>(null)
  const [height, setHeight] = useState(fallback)

  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(([entry]) => {
      if (entry && entry.contentRect.height > 0) setHeight(entry.contentRect.height)
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  return { ref, height }
}
