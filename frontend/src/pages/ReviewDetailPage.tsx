import { Link, useParams } from 'react-router'
import { fetchAnalysis } from '../api/resume'
import AnalysisReport from '../components/AnalysisReport'
import { ErrorState, Loading } from '../components/ui/Feedback'
import PageHeader from '../components/ui/PageHeader'
import { useResource } from '../hooks/useResource'

/** One saved quick review, loaded from the database without calling the AI again. */
export default function ReviewDetailPage() {
  const { analysisId = '' } = useParams()
  const { state, reload } = useResource(`analysis:${analysisId}`, () => fetchAnalysis(analysisId))
  return (
    <div>
      <PageHeader
        title="Quick review"
        documentTitle={state.data ? `${state.data.resume_filename} – quick review` : 'Quick review'}
        actions={
          <Link className="btn-small is-secondary" to="/reviews">
            All quick reviews
          </Link>
        }
      />
      {state.status === 'loading' && !state.data && <Loading>Loading the review…</Loading>}
      {state.status === 'error' && (
        <ErrorState
          error={state.error}
          onRetry={reload}
          resource="review"
          back={{ to: '/reviews', label: 'Back to quick reviews' }}
        />
      )}
      {state.data && <AnalysisReport record={state.data} />}
    </div>
  )
}
