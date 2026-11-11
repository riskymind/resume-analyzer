import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { deleteMatch, fetchMatch } from '../api/jobs'
import MatchReport from '../components/MatchReport'
import { useConfirm } from '../components/ui/ConfirmDialog'
import { ErrorState, Flag, Loading } from '../components/ui/Feedback'
import PageHeader from '../components/ui/PageHeader'
import { useResource } from '../hooks/useResource'
import { formatDateTime } from '../utils/format'

/** A saved deterministic match report, with links to the resume, the job and a targeted rewrite. */
export default function MatchDetailPage() {
  const { matchId = '' } = useParams()
  const navigate = useNavigate()
  const { state, reload } = useResource(`match:${matchId}`, () => fetchMatch(matchId))
  const { confirm, dialog } = useConfirm()
  const [error, setError] = useState<string | null>(null)
  const match = state.data

  async function remove() {
    if (!match) return
    const ok = await confirm({
      title: 'Delete this match report?',
      body: <p>The resume and the job description are kept.</p>,
      confirmLabel: 'Delete report',
      danger: true,
    })
    if (!ok) return
    try {
      await deleteMatch(match.id)
      navigate('/matches', { replace: true })
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <div>
      <PageHeader
        title="Job match report"
        documentTitle={match ? `Match: ${match.job_title || 'job description'}` : 'Job match report'}
        meta={
          match && (
            <p className="report-meta">
              <Link to={`/resumes/${match.resume_id}`}>{match.resume_filename}</Link> vs.{' '}
              <Link to={`/jobs/${match.job_id}`}>{match.job_title || 'job description'}</Link> · matched{' '}
              {formatDateTime(match.created_at)}
            </p>
          )
        }
        actions={
          match && (
            <>
              <Link className="btn-small" to={`/rewrite?resume=${match.resume_id}&job=${match.job_id}`}>
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
      {state.status === 'loading' && !match && <Loading>Loading the match report…</Loading>}
      {state.status === 'error' && (
        <ErrorState
          error={state.error}
          onRetry={reload}
          resource="match report"
          back={{ to: '/matches', label: 'Back to saved matches' }}
        />
      )}
      {match && <MatchReport match={match} />}
    </div>
  )
}
