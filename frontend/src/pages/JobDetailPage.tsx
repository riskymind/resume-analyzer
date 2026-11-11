import { useState, type CSSProperties } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { deleteJob, fetchJob, fetchMatches } from '../api/jobs'
import JobRequirements from '../components/JobRequirements'
import { JOB_DELETE_BODY } from '../components/SavedMatches'
import { useConfirm } from '../components/ui/ConfirmDialog'
import { EmptyState, ErrorState, Flag, Loading } from '../components/ui/Feedback'
import PageHeader from '../components/ui/PageHeader'
import { useResource } from '../hooks/useResource'
import { formatDate, formatDateTime } from '../utils/format'
import { scoreColor } from '../utils/score'

/** A saved job description: its verified requirements, its match reports and next steps. */
export default function JobDetailPage() {
  const { jobId = '' } = useParams()
  const navigate = useNavigate()
  const { state, reload } = useResource(`job:${jobId}`, () => fetchJob(jobId))
  const matches = useResource(`job-matches:${jobId}`, () => fetchMatches({ jobId }))
  const { confirm, dialog } = useConfirm()
  const [error, setError] = useState<string | null>(null)
  const job = state.data

  async function remove() {
    if (!job) return
    const ok = await confirm({
      title: `Delete “${job.title || 'this job description'}”?`,
      body: JOB_DELETE_BODY(job),
      confirmLabel: 'Delete job description',
      danger: true,
    })
    if (!ok) return
    try {
      await deleteJob(job.id)
      navigate('/matches', { replace: true })
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <div>
      <PageHeader
        title="Job description"
        documentTitle={job?.title || 'Job description'}
        meta={
          job && (
            <p className="report-meta">
              Saved {formatDate(job.created_at)} · {job.source === 'pasted' ? 'pasted text' : `from ${job.source}`}
            </p>
          )
        }
        actions={
          job && (
            <>
              <Link className="btn-small" to={`/match?job=${job.id}`}>
                Match a resume
              </Link>
              <Link className="btn-small" to={`/rewrite?job=${job.id}`}>
                Rewrite for this job
              </Link>
              <button type="button" className="btn-small is-secondary" onClick={remove}>
                Delete
              </button>
            </>
          )
        }
      />
      {dialog}
      <Flag message={error} />
      {state.status === 'loading' && !job && <Loading>Loading the job description…</Loading>}
      {state.status === 'error' && (
        <ErrorState
          error={state.error}
          onRetry={reload}
          resource="job description"
          back={{ to: '/matches', label: 'Back to saved jobs' }}
        />
      )}
      {job && (
        <>
          <JobRequirements job={job} />
          <section aria-labelledby="job-matches-title" className="related">
            <h2 id="job-matches-title" className="section-title">
              Match reports for this job
            </h2>
            {matches.state.status === 'loading' && !matches.state.data && <Loading />}
            {matches.state.status === 'error' && <ErrorState error={matches.state.error} onRetry={matches.reload} />}
            {matches.state.data?.length === 0 && <EmptyState>No resume has been matched to this job yet.</EmptyState>}
            {matches.state.data && matches.state.data.length > 0 && (
              <ul className="ledger">
                {matches.state.data.map((match) => (
                  <li key={match.id}>
                    <Link className="ledger-row" to={`/matches/${match.id}`}>
                      <span className="ledger-filename">{match.resume_filename}</span>
                      <span className="ledger-date">{formatDateTime(match.created_at)}</span>
                      <span
                        className="ledger-score"
                        style={{ '--seal-color': scoreColor(match.match_score) } as CSSProperties}
                      >
                        {match.match_score}% — {match.label}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  )
}
