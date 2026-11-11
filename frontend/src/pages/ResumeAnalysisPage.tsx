import { useState, type CSSProperties } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router'
import { fetchMatches } from '../api/jobs'
import { deleteResume, fetchResume } from '../api/resume'
import { fetchRewrites } from '../api/rewrites'
import QualityReport from '../components/QualityReport'
import { useConfirm } from '../components/ui/ConfirmDialog'
import { EmptyState, ErrorState, Flag, Loading, SuccessNote } from '../components/ui/Feedback'
import PageHeader from '../components/ui/PageHeader'
import { useResource } from '../hooks/useResource'
import type { ResumeDetail } from '../types/api'
import { formatDate, formatDateTime } from '../utils/format'
import { scoreColor } from '../utils/score'
import type { UploadedState } from './UploadPage'

/** Job matches and rewrites made from this resume. */
function RelatedWork({ resume }: { resume: ResumeDetail }) {
  const matches = useResource(`matches:${resume.id}`, () => fetchMatches({ resumeId: resume.id }))
  const rewrites = useResource('rewrites', fetchRewrites)
  const ownRewrites = rewrites.state.data?.filter((rewrite) => rewrite.resume_id === resume.id)

  return (
    <section className="related" aria-labelledby="related-title">
      <h2 id="related-title" className="section-title">
        Job matches and rewrites
      </h2>
      <p className="quality-intro">
        A job match percentage measures fit with one job description. It is a different number from the quality score
        above.
      </p>

      <h3 className="sub-head">Job matches</h3>
      {matches.state.status === 'loading' && !matches.state.data && <Loading />}
      {matches.state.status === 'error' && <ErrorState error={matches.state.error} onRetry={matches.reload} />}
      {matches.state.data?.length === 0 && (
        <EmptyState
          action={
            <Link className="btn-small is-secondary" to={`/match?resume=${resume.id}`}>
              Match against a job
            </Link>
          }
        >
          This resume hasn't been matched to a job yet.
        </EmptyState>
      )}
      {matches.state.data && matches.state.data.length > 0 && (
        <ul className="ledger">
          {matches.state.data.map((match) => (
            <li key={match.id}>
              <Link className="ledger-row" to={`/matches/${match.id}`}>
                <span className="ledger-filename">{match.job_title || 'Job description'}</span>
                <span className="ledger-date">{formatDateTime(match.created_at)}</span>
                <span
                  className="ledger-score"
                  style={{ '--seal-color': scoreColor(match.match_score) } as CSSProperties}
                >
                  {match.match_score}% match · {match.label}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}

      <h3 className="sub-head">Rewrites</h3>
      {rewrites.state.status === 'loading' && !rewrites.state.data && <Loading />}
      {rewrites.state.status === 'error' && <ErrorState error={rewrites.state.error} onRetry={rewrites.reload} />}
      {ownRewrites?.length === 0 && (
        <EmptyState
          action={
            <Link className="btn-small is-secondary" to={`/rewrite?resume=${resume.id}`}>
              Rewrite this resume
            </Link>
          }
        >
          No rewrites of this resume yet.
        </EmptyState>
      )}
      {ownRewrites && ownRewrites.length > 0 && (
        <ul className="ledger">
          {ownRewrites.map((rewrite) => (
            <li key={rewrite.id}>
              <Link className="ledger-row" to={`/rewrites/${rewrite.id}`}>
                <span className="ledger-filename">{rewrite.name}</span>
                <span className="ledger-date">{formatDateTime(rewrite.updated_at)}</span>
                <span className="ledger-score">
                  v{rewrite.current_version} · quality {rewrite.quality_before}→{rewrite.quality_after}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** One resume's job-independent quality analysis, with links to match it to a job or rewrite it. */
export default function ResumeAnalysisPage() {
  const { resumeId = '' } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const { state, reload } = useResource(`resume:${resumeId}`, () => fetchResume(resumeId))
  const { confirm, dialog } = useConfirm()
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const justUploaded = (location.state as UploadedState | null)?.uploaded === true
  const resume = state.data

  async function remove() {
    if (!resume) return
    const ok = await confirm({
      title: `Delete “${resume.filename}”?`,
      body: (
        <p>
          This deletes the resume's extracted text and analysis, its job match reports and quick reviews, and every
          rewrite made from it. Saved job descriptions are kept. This cannot be undone.
        </p>
      ),
      confirmLabel: 'Delete resume',
      danger: true,
    })
    if (!ok) return
    setDeleting(true)
    setDeleteError(null)
    try {
      await deleteResume(resume.id)
      navigate('/resumes', { replace: true })
    } catch (err) {
      setDeleteError((err as Error).message)
      setDeleting(false)
    }
  }

  return (
    <div className="analysis-page">
      <PageHeader
        title="Resume analysis"
        documentTitle={resume ? `${resume.filename} – analysis` : 'Resume analysis'}
        meta={
          resume && (
            <p className="report-meta">
              <strong>{resume.filename}</strong> · uploaded {formatDate(resume.created_at)} ·{' '}
              {resume.file_format.toUpperCase()}
              {resume.page_count ? ` · ${resume.page_count} page${resume.page_count === 1 ? '' : 's'}` : ''}
            </p>
          )
        }
        actions={
          resume && (
            <>
              <Link className="btn-small" to={`/match?resume=${resume.id}`}>
                Match against a job
              </Link>
              <Link className="btn-small" to={`/rewrite?resume=${resume.id}`}>
                Rewrite this resume
              </Link>
              <button type="button" className="btn-small is-secondary" onClick={remove} disabled={deleting}>
                {deleting ? 'Deleting…' : 'Delete'}
              </button>
            </>
          )
        }
      />
      {dialog}

      {state.status === 'loading' && !resume && <Loading>Loading the analysis…</Loading>}
      {state.status === 'error' && (
        <ErrorState
          error={state.error}
          onRetry={reload}
          resource="resume"
          back={{ to: '/resumes', label: 'Back to your resumes' }}
        />
      )}

      {resume && (
        <>
          {justUploaded && <SuccessNote>Resume uploaded and analysed.</SuccessNote>}
          <Flag message={deleteError} />
          {resume.warnings.map((warning, index) => (
            <p key={index} className="quality-note">
              {warning}
            </p>
          ))}
          {resume.sections.length > 0 && (
            <p className="report-meta">
              Sections found: {resume.sections.map((section) => section.heading || section.kind).join(' · ')}
            </p>
          )}

          {resume.quality ? (
            <QualityReport quality={resume.quality} resumeId={resume.id} resume={resume} />
          ) : (
            <p className="quality-note">This resume has no quality analysis yet.</p>
          )}

          <RelatedWork resume={resume} />
        </>
      )}
    </div>
  )
}
