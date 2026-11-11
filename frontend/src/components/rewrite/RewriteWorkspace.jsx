import { useState } from 'react'
import { fetchRewrite, regenerateRewrite, updateRewrite } from '../../api/rewrites'
import { Flag } from '../DocumentPickers'
import ExportPanel from './ExportPanel'
import ScoreComparison from './ScoreComparison'
import {
  ContactSection,
  EducationSection,
  ExperienceSection,
  ProjectsSection,
  SkillsSection,
  SummarySection,
} from './Sections'
import VerificationPanel from './VerificationPanel'
import { MODE_LABELS } from './options'

const SOURCE_LABELS = {
  generate: 'AI rewrite',
  regenerate: 'Regenerated',
  decisions: 'Reviewed suggestions',
  edit: 'Your edits',
  restore: 'Restored',
}

/** Review, edit, regenerate and export one rewrite. Every saved change becomes a new version. */
export default function RewriteWorkspace({ rewrite: initial, onChanged = undefined }) {
  const [rewrite, setRewrite] = useState(initial)
  const [viewing, setViewing] = useState(null) // an older version, read-only
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [selected, setSelected] = useState([])
  const [name, setName] = useState(initial.name)

  const shown = viewing || rewrite
  const readOnly = viewing !== null

  async function run(action, success) {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const next = await action()
      setRewrite(next)
      setViewing(null)
      setSelected([])
      if (success) setNotice(success)
      onChanged?.(next)
      return true
    } catch (err) {
      setError(err.message)
      if (err.status === 409 && err.code === 'conflict') {
        // Someone (another tab) saved first: load the latest so the user works on current data.
        fetchRewrite(rewrite.id)
          .then((latest) => {
            setRewrite(latest)
            setViewing(null)
            onChanged?.(latest)
          })
          .catch(() => {})
      }
      return false
    } finally {
      setBusy(false)
    }
  }

  const ctx = {
    content: shown.content,
    suggestions: shown.suggestions,
    readOnly,
    busy,
    onDecide: (id, decision) =>
      run(() => updateRewrite(rewrite.id, rewrite.current_version, { decisions: { [id]: decision } })),
    onSaveContent: (content) =>
      run(() => updateRewrite(rewrite.id, rewrite.current_version, { content }), 'Saved as a new version.'),
    onRegenerate: (scope, bulletIds = []) =>
      run(
        () => regenerateRewrite(rewrite.id, rewrite.current_version, { scope, bulletIds }),
        'New suggestions generated. Review them below.',
      ),
  }

  async function viewVersion(number) {
    if (number === rewrite.current_version) return setViewing(null)
    setBusy(true)
    try {
      setViewing(await fetchRewrite(rewrite.id, number))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const toggleBullet = (id) =>
    setSelected((current) => (current.includes(id) ? current.filter((x) => x !== id) : [...current, id]))

  return (
    <div className="rewrite-workspace">
      <header className="rewrite-head">
        <form
          className="rename-form"
          onSubmit={(event) => {
            event.preventDefault()
            if (name.trim() && name.trim() !== rewrite.name)
              run(() => updateRewrite(rewrite.id, rewrite.current_version, { name: name.trim() }), 'Renamed.')
          }}
        >
          <label className="visually-hidden" htmlFor="rewrite-name">
            Rewrite name
          </label>
          <input
            id="rewrite-name"
            className="rename-input"
            value={name}
            maxLength={120}
            onChange={(e) => setName(e.target.value)}
          />
          {name.trim() !== rewrite.name && (
            <button type="submit" className="btn-small" disabled={busy || !name.trim()}>
              Rename
            </button>
          )}
        </form>
        <p className="report-meta">
          {rewrite.resume_filename} ·{' '}
          {rewrite.job_title
            ? `targeting ${rewrite.job_title}`
            : rewrite.job_detached_at
              ? 'target job deleted'
              : 'general improvement'}{' '}
          · {MODE_LABELS[rewrite.mode]} · version {rewrite.current_version}
        </p>
        {rewrite.job_detached_at && (
          <p className="quality-note" role="note">
            The job this rewrite targeted was deleted on {new Date(rewrite.job_detached_at).toLocaleDateString()}. Your
            rewritten content and versions are kept; job-match scores, gaps and keyword analysis were removed, so no job
            match is shown.
          </p>
        )}
        <p className="report-meta">Your original resume is never changed. This rewrite is saved separately.</p>
      </header>

      <Flag message={error} />
      {notice && (
        <p className="success-note" role="status">
          {notice}
        </p>
      )}
      {busy && (
        <p className="empty-note" role="status">
          Working… AI requests can take up to a minute.
        </p>
      )}

      {readOnly && (
        <div className="quality-note version-banner">
          <span>
            Viewing version {viewing.version} (read-only). The current version is {rewrite.current_version}.
          </span>
          <button
            type="button"
            className="btn-small"
            disabled={busy}
            onClick={() =>
              run(
                () => updateRewrite(rewrite.id, rewrite.current_version, { restore_version: viewing.version }),
                `Version ${viewing.version} restored as a new version.`,
              )
            }
          >
            Restore this version
          </button>
          <button type="button" className="btn-small is-secondary" onClick={() => setViewing(null)}>
            Back to current
          </button>
        </div>
      )}

      <div className="rewrite-columns">
        <div className="rewrite-main">
          <ContactSection ctx={ctx} key={`contact-${shown.version}`} />
          <SummarySection ctx={ctx} key={`summary-${shown.version}`} />
          <ExperienceSection ctx={ctx} selected={selected} onToggle={toggleBullet} key={`exp-${shown.version}`} />
          <SkillsSection ctx={ctx} key={`skills-${shown.version}`} />
          <ProjectsSection ctx={ctx} key={`projects-${shown.version}`} />
          <EducationSection ctx={ctx} key={`edu-${shown.version}`} />
        </div>
        <aside className="rewrite-side">
          <ScoreComparison scores={shown.scores} />
          <VerificationPanel verification={shown.verification} generation={shown.generation} />
          <section className="rewrite-panel" aria-labelledby="versions-title">
            <h2 id="versions-title">Versions</h2>
            <ul className="version-list">
              {rewrite.versions.map((v) => (
                <li key={v.number}>
                  <button
                    type="button"
                    className={`version-row ${shown.version === v.number ? 'is-active' : ''}`}
                    onClick={() => viewVersion(v.number)}
                    disabled={busy}
                  >
                    <span>
                      v{v.number} · {SOURCE_LABELS[v.source] || v.source}
                    </span>
                    <small>
                      {new Date(v.created_at).toLocaleString()} · quality {v.quality_after}
                      {v.match_after != null ? ` · match ${v.match_after}%` : ''}
                    </small>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        </aside>
      </div>

      <ExportPanel
        rewrite={shown}
        version={readOnly ? viewing.version : null}
        readOnly={readOnly}
        busy={busy}
        onTemplateChange={(template) => run(() => updateRewrite(rewrite.id, rewrite.current_version, { template }))}
      />
    </div>
  )
}
