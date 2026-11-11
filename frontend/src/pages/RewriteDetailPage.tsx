import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { deleteRewrite, fetchRewrite } from '../api/rewrites'
import RewriteWorkspace from '../components/rewrite/RewriteWorkspace'
import { useConfirm } from '../components/ui/ConfirmDialog'
import { ErrorState, Flag, Loading } from '../components/ui/Feedback'
import PageHeader from '../components/ui/PageHeader'
import { useResource } from '../hooks/useResource'
import { REWRITE_DELETE_BODY } from './RewritesPage'

/**
 * The rewrite workspace for one saved rewrite: review suggestions, edit, regenerate, compare versions, preview and
 * export. Opening the page always loads the latest version, so changes made in another tab show up.
 */
export default function RewriteDetailPage() {
  const { rewriteId = '' } = useParams()
  const navigate = useNavigate()
  const { state, reload } = useResource(`rewrite:${rewriteId}`, () => fetchRewrite(rewriteId))
  const { confirm, dialog } = useConfirm()
  const [error, setError] = useState<string | null>(null)
  const rewrite = state.data

  async function remove() {
    if (!rewrite) return
    const ok = await confirm({
      title: `Delete “${rewrite.name}”?`,
      body: REWRITE_DELETE_BODY,
      confirmLabel: 'Delete rewrite',
      danger: true,
    })
    if (!ok) return
    try {
      await deleteRewrite(rewrite.id)
      navigate('/rewrites', { replace: true })
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <div className="rewrite-page">
      <PageHeader
        title="Rewrite workspace"
        documentTitle={rewrite ? `${rewrite.name} – rewrite` : 'Rewrite workspace'}
        meta={
          rewrite && (
            <p className="report-meta">
              From <Link to={`/resumes/${rewrite.resume_id}`}>{rewrite.resume_filename}</Link>
              {rewrite.job_id && (
                <>
                  {' '}
                  · targeting <Link to={`/jobs/${rewrite.job_id}`}>{rewrite.job_title || 'job description'}</Link>
                </>
              )}
            </p>
          )
        }
        actions={
          rewrite && (
            <>
              <Link className="btn-small is-secondary" to="/rewrites">
                All rewrites
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
      {state.status === 'loading' && !rewrite && <Loading>Loading the rewrite…</Loading>}
      {state.status === 'error' && (
        <ErrorState
          error={state.error}
          onRetry={reload}
          resource="rewrite"
          back={{ to: '/rewrites', label: 'Back to saved rewrites' }}
        />
      )}
      {rewrite && <RewriteWorkspace key={rewrite.id} rewrite={rewrite} />}
    </div>
  )
}
