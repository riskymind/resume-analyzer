import { useState, type DragEvent } from 'react'

interface FileDropzoneProps {
  id: string
  file: File | null
  onFile: (file: File) => void
  /** Called when more than one file is dropped. */
  onMultiple?: () => void
  disabled?: boolean
  invalid?: boolean
  describedBy?: string
  accept?: string
  prompt?: string
}

/**
 * Drag-and-drop target around a real file input. The input stays in the tab order (it is only visually
 * hidden), so keyboard and screen-reader users choose a file the normal way; dragging is an extra, not a
 * requirement.
 */
export default function FileDropzone({
  id,
  file,
  onFile,
  onMultiple,
  disabled = false,
  invalid = false,
  describedBy,
  accept = '.pdf,.docx,.md',
  prompt = 'Drag and drop your resume here',
}: FileDropzoneProps) {
  const [dragging, setDragging] = useState(false)

  function onDragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    if (!disabled) setDragging(true)
  }

  function onDragLeave(event: DragEvent<HTMLDivElement>) {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false)
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragging(false)
    if (disabled) return
    const files = event.dataTransfer.files
    if (files.length > 1) onMultiple?.()
    const first = files[0]
    if (first && files.length === 1) onFile(first)
  }

  return (
    <div
      className={`dropzone ${dragging ? 'is-dragging' : ''} ${file ? 'has-file' : ''} ${invalid ? 'is-invalid' : ''}`}
      onDragEnter={onDragOver}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      data-testid="dropzone"
    >
      <input
        id={id}
        className="dropzone-input"
        type="file"
        accept={accept}
        disabled={disabled}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        onChange={(event) => {
          const chosen = event.target.files?.[0]
          if (chosen) onFile(chosen)
          // Allow choosing the same file again after an error.
          event.target.value = ''
        }}
      />
      <label htmlFor={id} className="dropzone-label">
        <span className="dropzone-title">{file ? file.name : prompt}</span>{' '}
        <span className="dropzone-action">{file ? 'Choose a different file' : 'or choose a file'}</span>
      </label>
    </div>
  )
}
