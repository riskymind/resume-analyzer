import { useEffect } from 'react'

const APP_NAME = 'Resume Analyzer'

/** Sets the browser tab title, so screen-reader users and tab lists can tell pages apart. */
export function usePageTitle(title: string | null | undefined): void {
  useEffect(() => {
    document.title = title ? `${title} · ${APP_NAME}` : APP_NAME
  }, [title])
}
