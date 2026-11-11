import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from 'react'

export interface ConfirmOptions {
  title: string
  body?: ReactNode
  confirmLabel: string
  /** Styles the confirm button as destructive. */
  danger?: boolean
}

interface ConfirmDialogProps extends ConfirmOptions {
  onClose: (confirmed: boolean) => void
}

/**
 * A modal confirmation built on the native <dialog> element: the browser traps focus, makes the rest of the page
 * inert, closes it on Escape and returns focus to the button that opened it. Cancel is focused first, so pressing
 * Enter by accident never deletes anything.
 */
export function ConfirmDialog({ title, body, confirmLabel, danger = false, onClose }: ConfirmDialogProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  const bodyId = useId()

  useEffect(() => {
    const dialog = ref.current
    if (dialog && !dialog.open) dialog.showModal()
    return () => {
      if (dialog?.open) dialog.close()
    }
  }, [])

  return (
    <dialog
      ref={ref}
      className="confirm-dialog"
      aria-labelledby={titleId}
      aria-describedby={body ? bodyId : undefined}
      onCancel={(event) => {
        event.preventDefault()
        onClose(false)
      }}
    >
      <h2 id={titleId} className="confirm-title">
        {title}
      </h2>
      {body && (
        <div id={bodyId} className="confirm-body">
          {body}
        </div>
      )}
      <div className="confirm-actions">
        {/* eslint-disable-next-line jsx-a11y/no-autofocus -- the safe choice is focused when the dialog opens */}
        <button type="button" className="btn-small is-secondary" autoFocus onClick={() => onClose(false)}>
          Cancel
        </button>
        <button type="button" className={`btn-small ${danger ? 'is-danger' : ''}`} onClick={() => onClose(true)}>
          {confirmLabel}
        </button>
      </div>
    </dialog>
  )
}

/**
 * `const { confirm, dialog } = useConfirm()`; render `{dialog}` and `await confirm({...})` → true when confirmed.
 */
export function useConfirm() {
  const [request, setRequest] = useState<{ options: ConfirmOptions; resolve: (ok: boolean) => void } | null>(null)

  const confirm = useCallback(
    (options: ConfirmOptions) => new Promise<boolean>((resolve) => setRequest({ options, resolve })),
    [],
  )

  const dialog = request ? (
    <ConfirmDialog
      {...request.options}
      onClose={(ok) => {
        request.resolve(ok)
        setRequest(null)
      }}
    />
  ) : null

  return { confirm, dialog }
}
