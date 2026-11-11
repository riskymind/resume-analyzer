import { useCallback, useEffect, useRef, useState } from 'react'

export type ResourceState<T> =
  | { status: 'loading'; data: T | null; error: null }
  | { status: 'success'; data: T; error: null }
  | { status: 'error'; data: T | null; error: Error }

export interface Resource<T> {
  state: ResourceState<T>
  /** Loads again (e.g. a Retry button). Keeps showing the previous data while it loads. */
  reload: () => void
  /** Replaces the loaded data locally, e.g. after a successful update returned the new value. */
  setData: (data: T) => void
}

/**
 * Loads data for a page or panel. `key` identifies what is loaded: when it changes, the previous result is
 * discarded and `load` runs again; `null` means "nothing to load yet" (stays in `loading`). Late responses for an
 * older key are ignored, so fast navigation never shows another resource's data.
 */
export function useResource<T>(key: string | null, load: () => Promise<T>): Resource<T> {
  const [state, setState] = useState<ResourceState<T>>({ status: 'loading', data: null, error: null })
  const [attempt, setAttempt] = useState(0)
  const loadRef = useRef(load)
  const [loadedKey, setLoadedKey] = useState(key)

  useEffect(() => {
    loadRef.current = load
  })

  // A different resource: drop the old data during render so it is never shown under the new key.
  if (loadedKey !== key) {
    setLoadedKey(key)
    setState({ status: 'loading', data: null, error: null })
  }

  useEffect(() => {
    if (key === null) return
    let cancelled = false
    loadRef.current().then(
      (data) => {
        if (!cancelled) setState({ status: 'success', data, error: null })
      },
      (error: unknown) => {
        if (!cancelled) {
          setState((current) => ({
            status: 'error',
            data: current.data,
            error: error instanceof Error ? error : new Error(String(error)),
          }))
        }
      },
    )
    return () => {
      cancelled = true
    }
  }, [key, attempt])

  const reload = useCallback(() => {
    setState((current) => ({ status: 'loading', data: current.data, error: null }))
    setAttempt((value) => value + 1)
  }, [])

  const setData = useCallback((data: T) => setState({ status: 'success', data, error: null }), [])

  return { state, reload, setData }
}
