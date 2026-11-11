import type { ReactNode } from 'react'
import { usePageTitle } from '../../hooks/usePageTitle'

interface PageHeaderProps {
  title: string
  /** Shown under the title (e.g. the file name). */
  meta?: ReactNode
  /** Buttons and links for the page's main actions. */
  actions?: ReactNode
  /** Browser tab title, when it should differ from the heading. */
  documentTitle?: string
}

/**
 * The page's single <h1>. It is focusable (tabIndex -1) so the layout can move focus to it after navigation,
 * which tells screen-reader users that the page changed.
 */
export default function PageHeader({ title, meta, actions, documentTitle }: PageHeaderProps) {
  usePageTitle(documentTitle ?? title)
  return (
    <header className="page-header">
      <div className="page-header-text">
        <h1 tabIndex={-1} className="page-title">
          {title}
        </h1>
        {meta && <div className="page-meta">{meta}</div>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  )
}
