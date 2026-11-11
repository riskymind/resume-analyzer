import { useState, type CSSProperties } from 'react'
import { Link } from 'react-router'
import { deleteJob, deleteMatch, fetchJobs, fetchMatches } from '../api/jobs'
import { useResource } from '../hooks/useResource'
import type { JobSummary, MatchSummary } from '../types/api'
import { formatDateTime, plural } from '../utils/format'
import { scoreColor } from '../utils/score'
import { useConfirm } from './ui/ConfirmDialog'
import { EmptyState, ErrorState, Flag, Loading } from './ui/Feedback'

export const JOB_DELETE_BODY = (job: { match_count: number }) => (
  <p>
    Its requirements and {plural(job.match_count, 'match report')} are deleted. Rewrites that targeted it are kept, but
    their job-specific scores, gaps and keyword analysis are removed. This cannot be undone.
  </p>
)

/** Saved match reports and job descriptions, each linking to its own page, with deletion. */
export default function SavedMatches() {
  const matches = useResource('matches', () => fetchMatches())
  const jobs = useResource('jobs', fetchJobs)
  const { confirm, dialog } = useConfirm()
  const [error, setError] = useState<string | null>(null)

  async function removeMatch(match: MatchSummary) {
    const ok = await confirm({
      title: 'Delete this match report?',
      body: (
        <p>
          The report for “{match.job_title || 'job description'}” and {match.resume_filename} is deleted. The resume and
          job description are kept.
        </p>
      ),
      confirmLabel: 'Delete report',
      danger: true,
    })
    if (!ok) return
    try {
      setError(null)
      await deleteMatch(match.id)
      matches.reload()
      jobs.reload()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function removeJob(job: JobSummary) {
    const ok = await confirm({
      title: `Delete “${job.title || 'this job description'}”?`,
      body: JOB_DELETE_BODY(job),
      confirmLabel: 'Delete job description',
      danger: true,
    })
    if (!ok) return
    try {
      setError(null)
      await deleteJob(job.id)
      matches.reload()
      jobs.reload()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <div>
      {dialog}
      <Flag message={error} />

      <section aria-labelledby="saved-matches-title">
        <h2 id="saved-matches-title" className="ledger-title">
          Match reports
        </h2>
        {matches.state.status === 'loading' && !matches.state.data && <Loading>Loading match reports…</Loading>}
        {matches.state.status === 'error' && <ErrorState error={matches.state.error} onRetry={matches.reload} />}
        {matches.state.data?.length === 0 && (
          <EmptyState
            action={
              <Link className="btn-small is-secondary" to="/match">
                Run a job match
              </Link>
            }
          >
            No match reports yet.
          </EmptyState>
        )}
        {matches.state.data && matches.state.data.length > 0 && (
          <ul className="ledger">
            {matches.state.data.map((match) => (
              <li key={match.id} className="ledger-item">
                <Link className="ledger-row" to={`/matches/${match.id}`}>
                  <span className="ledger-filename">
                    {match.job_title || 'Job description'} · {match.resume_filename}
                  </span>
                  <span className="ledger-date">{formatDateTime(match.created_at)}</span>
                  <span
                    className="ledger-score"
                    style={{ '--seal-color': scoreColor(match.match_score) } as CSSProperties}
                  >
                    {match.match_score}% — {match.label}
                  </span>
                </Link>
                <button
                  type="button"
                  className="btn-quiet ledger-delete"
                  onClick={() => removeMatch(match)}
                  aria-label={`Delete match report: ${match.job_title || 'job description'}, ${match.resume_filename}`}
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="saved-jobs-title">
        <h2 id="saved-jobs-title" className="ledger-title">
          Job descriptions
        </h2>
        {jobs.state.status === 'loading' && !jobs.state.data && <Loading>Loading job descriptions…</Loading>}
        {jobs.state.status === 'error' && <ErrorState error={jobs.state.error} onRetry={jobs.reload} />}
        {jobs.state.data?.length === 0 && <EmptyState>No saved job descriptions yet.</EmptyState>}
        {jobs.state.data && jobs.state.data.length > 0 && (
          <ul className="ledger">
            {jobs.state.data.map((job) => (
              <li key={job.id} className="ledger-item">
                <Link className="ledger-row" to={`/jobs/${job.id}`}>
                  <span className="ledger-filename">
                    {job.title || 'Untitled'}
                    {job.company ? ` · ${job.company}` : ''}
                  </span>
                  <span className="ledger-date">{formatDateTime(job.created_at)}</span>
                  <span className="ledger-score">
                    {plural(job.requirement_count, 'requirement')} · {plural(job.match_count, 'match', 'matches')}
                  </span>
                </Link>
                <button
                  type="button"
                  className="btn-quiet ledger-delete"
                  onClick={() => removeJob(job)}
                  aria-label={`Delete job description: ${job.title || 'Untitled'}`}
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
