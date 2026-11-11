import { useId, useRef, type KeyboardEvent, type ReactNode } from 'react'

export interface TabItem<K extends string> {
  key: K
  label: string
}

interface TabsProps<K extends string> {
  /** Accessible name of the tab list. */
  label: string
  items: TabItem<K>[]
  value: K
  onChange: (key: K) => void
  /** The content of the selected tab. */
  children?: ReactNode
}

/**
 * WAI-ARIA tabs: arrow keys, Home and End move between tabs (selection follows focus), Tab moves into the
 * panel. Used where one of several alternative inputs is shown in the same place (e.g. paste vs upload).
 */
export default function Tabs<K extends string>({ label, items, value, onChange, children }: TabsProps<K>) {
  const base = useId()
  const refs = useRef<Record<string, HTMLButtonElement | null>>({})
  const tabId = (key: string) => `${base}-tab-${key}`
  const panelId = `${base}-panel`

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const index = items.findIndex((item) => item.key === value)
    const last = items.length - 1
    const next =
      event.key === 'ArrowRight'
        ? index === last
          ? 0
          : index + 1
        : event.key === 'ArrowLeft'
          ? index === 0
            ? last
            : index - 1
          : event.key === 'Home'
            ? 0
            : event.key === 'End'
              ? last
              : null
    if (next === null) return
    event.preventDefault()
    const target = items[next]
    if (!target) return
    onChange(target.key)
    refs.current[target.key]?.focus()
  }

  return (
    <>
      <div className="mode-tabs" role="tablist" aria-label={label}>
        {items.map((item) => {
          const selected = item.key === value
          return (
            <button
              key={item.key}
              ref={(node) => {
                refs.current[item.key] = node
              }}
              id={tabId(item.key)}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-controls={panelId}
              tabIndex={selected ? 0 : -1}
              className={selected ? 'is-active' : ''}
              onClick={() => onChange(item.key)}
              onKeyDown={onKeyDown}
            >
              {item.label}
            </button>
          )
        })}
      </div>
      <div role="tabpanel" id={panelId} aria-labelledby={tabId(value)} className="tab-panel">
        {children}
      </div>
    </>
  )
}
