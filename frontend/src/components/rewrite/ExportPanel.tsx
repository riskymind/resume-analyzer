import { useEffect, useId, useState } from 'react'
import { downloadExport, fetchPreview, fetchTemplates } from '../../api/rewrites'
import type {
  ExportFormat,
  RewriteDetail,
  TemplateInfo,
  TemplateKey,
  VerificationIssue,
  VerificationSummary,
} from '../../types/api'

/** Claims in the saved content that could not be verified: the user's own edits and accepted warnings. */
export function unverifiedClaims(verification: VerificationSummary): VerificationIssue[] {
  return verification.issues.filter((issue) => issue.severity === 'blocking' || issue.severity === 'warning')
}

interface ExportPanelProps {
  rewrite: RewriteDetail
  /** The older version being viewed (read-only), or null for the current version. */
  version: number | null
  readOnly: boolean
  busy: boolean
  onTemplateChange: (template: TemplateKey) => void
}

/** The last preview response, tagged with the request it answers. */
type PreviewResult = { key: string; html: string; error: string | null }

/**
 * Template choice, live preview and downloads. The preview is the same HTML
 * the server turns into the PDF, shown in a sandboxed iframe (no scripts, no
 * same-origin access).
 *
 * When the version contains claims that could not be verified against the
 * original resume, downloads stay disabled until the user confirms they have
 * checked them. Nothing is removed from their content; the server enforces the
 * same rule (409 acknowledgement_required) and records the confirmation. The
 * confirmation is never sent unless the user ticked the box for this version.
 */
export default function ExportPanel({ rewrite, version, readOnly, onTemplateChange, busy }: ExportPanelProps) {
  const [templates, setTemplates] = useState<TemplateInfo[]>([])
  const [template, setTemplate] = useState<TemplateKey>(rewrite.template)
  const [preview, setPreview] = useState<PreviewResult | null>(null)
  const [download, setDownload] = useState<{ format: ExportFormat | null; error: string | null; saved: string | null }>(
    { format: null, error: null, saved: null },
  )
  const [acknowledged, setAcknowledged] = useState(false)
  const [ackKey, setAckKey] = useState(`${rewrite.id}:${version || rewrite.version}`)
  const exportVersion = version || rewrite.version
  const warningTitleId = useId()

  // A confirmation applies to the content the user reviewed, so it resets whenever the version changes.
  const currentAckKey = `${rewrite.id}:${exportVersion}`
  if (ackKey !== currentAckKey) {
    setAckKey(currentAckKey)
    setAcknowledged(false)
  }

  const [syncedTemplate, setSyncedTemplate] = useState(rewrite.template)
  if (syncedTemplate !== rewrite.template) {
    setSyncedTemplate(rewrite.template)
    setTemplate(rewrite.template)
  }

  useEffect(() => {
    fetchTemplates()
      .then(setTemplates)
      .catch(() => setTemplates([]))
  }, [])

  // The preview is loading until a response for the current request arrives; the previous preview stays visible
  // meanwhile, so switching templates does not flash an empty frame.
  const previewKey = `${rewrite.id}:${template}:${version ?? ''}:${rewrite.current_version}`
  useEffect(() => {
    let cancelled = false
    fetchPreview(rewrite.id, { template, version })
      .then((body) => !cancelled && setPreview({ key: previewKey, html: body.html, error: null }))
      .catch((err: Error) => !cancelled && setPreview({ key: previewKey, html: '', error: err.message }))
    return () => {
      cancelled = true
    }
  }, [previewKey, rewrite.id, template, version])
  const previewStatus = preview?.key !== previewKey ? 'loading' : preview.error ? 'error' : 'success'

  function choose(key: TemplateKey) {
    setTemplate(key)
    if (!readOnly && key !== rewrite.template) onTemplateChange(key)
  }

  async function save(format: ExportFormat) {
    setDownload({ format, error: null, saved: null })
    try {
      const filename = await downloadExport(rewrite.id, {
        format,
        template,
        version: exportVersion,
        acknowledgeUnverified: acknowledged,
      })
      setDownload({ format: null, error: null, saved: filename })
    } catch (err) {
      setDownload({ format: null, error: (err as Error).message, saved: null })
    }
  }

  const pending = rewrite.verification.pending_review
  const claims = unverifiedClaims(rewrite.verification)
  const needsAcknowledgement = claims.length > 0
  const userClaims = claims.filter((issue) => issue.origin === 'user').length
  const downloadsBlocked = download.format !== null || (needsAcknowledgement && !acknowledged)

  return (
    <section className="rewrite-panel" aria-labelledby="export-title">
      <h2 id="export-title" className="panel-title">
        Template, preview and download
      </h2>
      <fieldset className="template-choice">
        <legend className="sub-head">Template</legend>
        {templates.map((item) => (
          <label key={item.key} className={`template-option ${template === item.key ? 'is-active' : ''}`}>
            <input
              type="radio"
              name="template"
              value={item.key}
              checked={template === item.key}
              onChange={() => choose(item.key)}
              disabled={busy}
            />
            <span>
              <strong>{item.name}</strong>
              <small>{item.description}</small>
            </span>
          </label>
        ))}
      </fieldset>

      <div className="preview-frame-wrap" aria-busy={previewStatus === 'loading'}>
        {previewStatus === 'loading' && (
          <p className="empty-note" role="status">
            Rendering preview…
          </p>
        )}
        {previewStatus === 'error' && (
          <p className="form-flag" role="alert">
            <span>{preview?.error}</span>
          </p>
        )}
        {preview?.html && <iframe title="Resume preview" className="preview-frame" sandbox="" srcDoc={preview.html} />}
      </div>

      {pending > 0 && (
        <p className="quality-note">
          {pending} suggestion(s) still need your review; only accepted or verified changes are exported.
        </p>
      )}
      {needsAcknowledgement && (
        <div className="export-warning" role="alert" aria-labelledby={warningTitleId}>
          <p id={warningTitleId} className="export-warning-title">
            {claims.length} claim{claims.length === 1 ? '' : 's'} in this version could not be verified against your
            original resume
          </p>
          <p className="report-meta">
            {userClaims > 0 && `${userClaims} come${userClaims === 1 ? 's' : ''} from your own edits. `}
            These are not marked as verified. They stay in your resume exactly as written; nothing is removed for you.
          </p>
          <ul className="export-warning-list">
            {claims.map((issue, index) => (
              <li key={`${issue.code}-${issue.unit}-${index}`}>
                <span className="issue-tag">
                  {issue.severity === 'blocking' ? 'Unverified' : 'Check'}
                  {issue.origin === 'user' ? ' · your edit' : ' · accepted suggestion'}
                </span>{' '}
                {issue.message}
              </li>
            ))}
          </ul>
          <label className="ack-check">
            <input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} />
            <span>
              I have checked these claims and confirm they are accurate. I understand they could not be verified against
              my original resume.
            </span>
          </label>
        </div>
      )}
      <div className="submit-row">
        <button
          type="button"
          className="btn-primary"
          onClick={() => save('pdf')}
          disabled={downloadsBlocked}
          aria-describedby={needsAcknowledgement && !acknowledged ? 'export-blocked-hint' : undefined}
        >
          {download.format === 'pdf' ? 'Preparing PDF…' : 'Download PDF'}
        </button>
        <button
          type="button"
          className="btn-primary is-alt"
          onClick={() => save('docx')}
          disabled={downloadsBlocked}
          aria-describedby={needsAcknowledgement && !acknowledged ? 'export-blocked-hint' : undefined}
        >
          {download.format === 'docx' ? 'Preparing DOCX…' : 'Download DOCX'}
        </button>
      </div>
      {needsAcknowledgement && !acknowledged && (
        <p className="empty-note" id="export-blocked-hint">
          Confirm the claims above to enable downloads.
        </p>
      )}
      {download.format && (
        <p className="empty-note" role="status">
          Generating your {download.format.toUpperCase()}…
        </p>
      )}
      {download.saved && (
        <p className="success-note" role="status">
          Downloaded {download.saved}.
        </p>
      )}
      {download.error && (
        <p className="form-flag" role="alert">
          <span>{download.error}</span>
        </p>
      )}
      <p className="report-meta">
        Files are generated from version {exportVersion}
        {version ? '' : ' (your latest saved version)'} on demand and are not stored on the server.
      </p>
    </section>
  )
}
