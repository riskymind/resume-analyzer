import { Link } from 'react-router'
import { fetchAnalyses } from '../api/resume'
import HistoryList from '../components/HistoryList'
import { EmptyState, ErrorState, Loading } from '../components/ui/Feedback'
import PageHeader from '../components/ui/PageHeader'
import { useResource } from '../hooks/useResource'

/** Past quick reviews (resume and job description reviewed together in one step). */
export default function ReviewsPage() {
  const { state, reload } = useResource('analyses', fetchAnalyses)
  return (
    <div>
      <PageHeader
        title="Quick reviews"
        actions={
          <Link className="btn-small" to="/reviews/new">
            New quick review
          </Link>
        }
      />
      {state.status === 'loading' && !state.data && <Loading>Loading your reviews…</Loading>}
      {state.status === 'error' && <ErrorState error={state.error} onRetry={reload} />}
      {state.data?.length === 0 && (
        <EmptyState
          action={
            <Link className="btn-small is-secondary" to="/reviews/new">
              Run a quick review
            </Link>
          }
        >
          No quick reviews yet.
        </EmptyState>
      )}
      {state.data && state.data.length > 0 && <HistoryList items={state.data} />}
    </div>
  )
}
