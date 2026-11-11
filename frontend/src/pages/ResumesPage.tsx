import type { CSSProperties } from 'react'
import { Link } from 'react-router'
import { fetchResumes } from '../api/resume'
import { EmptyState, ErrorState, Loading } from '../components/ui/Feedback'
import PageHeader from '../components/ui/PageHeader'
import { useResource } from '../hooks/useResource'
import { formatDateTime, plural } from '../utils/format'
import { scoreColor } from '../utils/score'

/** Every saved resume with its latest quality and ATS scores; each opens its analysis. */
export default function ResumesPage() {
  const { state, reload } = useResource('resumes', fetchResumes)

  return (
    <div>
      <PageHeader
        title="Resume analysis"
        meta={
          <p className="report-meta">
            Quality scores judge each resume on its own. They don't depend on any job description.
          </p>
        }
        actions={
          <Link className="btn-small" to="/upload">
            Upload a resume
          </Link>
        }
      />

      {state.status === 'loading' && !state.data && <Loading>Loading your resumes…</Loading>}
      {state.status === 'error' && <ErrorState error={state.error} onRetry={reload} />}
      {state.data && state.data.length === 0 && (
        <EmptyState
          action={
            <Link className="btn-small" to="/upload">
              Upload your first resume
            </Link>
          }
        >
          No resumes yet. Upload one to see its quality score, ATS compatibility estimate and recommendations.
        </EmptyState>
      )}
      {state.data && state.data.length > 0 && (
        <>
          <h2 className="visually-hidden">Your resumes</h2>
          <p className="report-meta list-count">{plural(state.data.length, 'resume')}</p>
          <ul className="ledger" aria-label="Your resumes">
            {state.data.map((resume) => (
              <li key={resume.id}>
                <Link className="ledger-row" to={`/resumes/${resume.id}`}>
                  <span className="ledger-filename">{resume.filename}</span>
                  <span className="ledger-date">{formatDateTime(resume.created_at)}</span>
                  {resume.overall_score != null ? (
                    <span
                      className="ledger-score"
                      style={{ '--seal-color': scoreColor(resume.overall_score) } as CSSProperties}
                    >
                      quality {resume.overall_score}/100 · ATS {resume.ats_score}/100
                    </span>
                  ) : (
                    <span className="ledger-score">not scored</span>
                  )}
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}

      <p className="report-meta section-footnote">
        Looking for a resume reviewed together with a job description in one step?{' '}
        <Link to="/reviews">See your quick reviews</Link>.
      </p>
    </div>
  )
}
