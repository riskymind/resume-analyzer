import { useState } from 'react'
import { Link } from 'react-router'
import { deleteRewrite, fetchRewrites } from '../api/rewrites'
import SavedRewrites from '../components/rewrite/SavedRewrites'
import { useConfirm } from '../components/ui/ConfirmDialog'
import { EmptyState, ErrorState, Flag, Loading } from '../components/ui/Feedback'
import PageHeader from '../components/ui/PageHeader'
import { useResource } from '../hooks/useResource'
import type { RewriteSummary } from '../types/api'

export const REWRITE_DELETE_BODY = (
  <p>All of its versions are deleted. Your original resume, its analysis and your job descriptions are not affected.</p>
)

export default function RewritesPage() {
  const { state, reload } = useResource('rewrites', fetchRewrites)
  const { confirm, dialog } = useConfirm()
  const [error, setError] = useState<string | null>(null)

  async function remove(item: RewriteSummary) {
    const ok = await confirm({
      title: `Delete “${item.name}”?`,
      body: REWRITE_DELETE_BODY,
      confirmLabel: 'Delete rewrite',
      danger: true,
    })
    if (!ok) return
    try {
      setError(null)
      await deleteRewrite(item.id)
      reload()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <div>
      <PageHeader
        title="Saved rewrites"
        actions={
          <Link className="btn-small" to="/rewrite">
            New rewrite
          </Link>
        }
      />
      {dialog}
      <Flag message={error} />
      {state.status === 'loading' && !state.data && <Loading>Loading saved rewrites…</Loading>}
      {state.status === 'error' && <ErrorState error={state.error} onRetry={reload} />}
      {state.data?.length === 0 && (
        <EmptyState
          action={
            <Link className="btn-small is-secondary" to="/rewrite">
              Start a rewrite
            </Link>
          }
        >
          No rewrites yet.
        </EmptyState>
      )}
      {state.data && state.data.length > 0 && <SavedRewrites items={state.data} onDelete={remove} />}
    </div>
  )
}
