import type { CSSProperties, ReactNode } from 'react'
import { Link } from 'react-router'
import { fetchJobs, fetchMatches } from '../api/jobs'
import { fetchAnalyses, fetchResume, fetchResumes } from '../api/resume'
import { fetchRewrites } from '../api/rewrites'
import { useUser } from '../auth/AuthContext'
import { EmptyState, ErrorState, Loading } from '../components/ui/Feedback'
import PageHeader from '../components/ui/PageHeader'
import ScoreSeal from '../components/ui/ScoreSeal'
import { useResource, type Resource } from '../hooks/useResource'
import type { ResumeSummary } from '../types/api'
import { formatDateTime, plural } from '../utils/format'
import { scoreColor } from '../utils/score'

const RECENT = 5

interface PanelProps<T> {
  id: string
  title: string
  resource: Resource<T[]>
  viewAll?: { to: string; label: string }
  empty: ReactNode
  emptyAction?: ReactNode
  children: (items: T[]) => ReactNode
}

/** One dashboard panel: its own loading, error (with retry) and empty states, so one failure never blanks the page. */
function Panel<T>({ id, title, resource, viewAll, empty, emptyAction, children }: PanelProps<T>) {
  const { state, reload } = resource
  return (
    <section className="dashboard-panel" aria-labelledby={id}>
      <header className="dashboard-panel-head">
        <h2 id={id}>{title}</h2>
        {viewAll && state.data && state.data.length > 0 && (
          <Link to={viewAll.to} className="dashboard-view-all">
            {viewAll.label}
          </Link>
        )}
      </header>
      {state.status === 'loading' && !state.data && <Loading />}
      {state.status === 'error' && <ErrorState error={state.error} onRetry={reload} />}
      {state.data?.length === 0 && <EmptyState action={emptyAction}>{empty}</EmptyState>}
      {state.data && state.data.length > 0 && children(state.data.slice(0, RECENT))}
    </section>
  )
}

/** The newest resume's scores and its most valuable fixes (from its stored quality report). */
function ResumeOverview({ latest, count }: { latest: ResumeSummary; count: number }) {
  const detail = useResource(`resume:${latest.id}`, () => fetchResume(latest.id))
  const fixes = detail.state.data?.quality?.recommendations.slice(0, 3) ?? []
  return (
    <div className="resume-overview">
      <div className="resume-overview-scores">
        {latest.overall_score != null ? (
          <ScoreSeal score={latest.overall_score} label="Resume quality" />
        ) : (
          <p className="report-meta">Not scored</p>
        )}
        <div>
          <p className="report-meta">
            Latest of {plural(count, 'resume')} · {formatDateTime(latest.created_at)}
          </p>
          <p className="resume-overview-name">
            <Link to={`/resumes/${latest.id}`}>{latest.filename}</Link>
          </p>
          {latest.ats_score != null && (
            <p className="report-meta">
              {latest.label} · ATS compatibility estimate {latest.ats_score}/100
            </p>
          )}
        </div>
      </div>
      {detail.state.status === 'error' && <ErrorState error={detail.state.error} onRetry={detail.reload} />}
      {fixes.length > 0 && (
        <div className="resume-overview-fixes">
          <h3 className="sub-head">Suggested improvements</h3>
          <ol className="fix-list">
            {fixes.map((fix, index) => (
              <li key={index}>
                <span>{fix.recommendation}</span>
                <small>up to +{fix.impact} points</small>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  )
}

/** Real activity only: everything shown comes from the user's saved data. */
export default function DashboardPage() {
  const user = useUser()
  const resumes = useResource('resumes', fetchResumes)
  const matches = useResource('matches', () => fetchMatches())
  const jobs = useResource('jobs', fetchJobs)
  const rewrites = useResource('rewrites', fetchRewrites)
  const reviews = useResource('analyses', fetchAnalyses)
  const hasResume = (resumes.state.data?.length ?? 0) > 0
  const latest = resumes.state.data?.[0]

  return (
    <div className="dashboard">
      <PageHeader title="Dashboard" meta={<p className="report-meta">Signed in as {user.email}</p>} />

      <nav className="quick-actions" aria-label="Start something">
        <Link className="quick-action" to="/upload">
          <strong>Upload a resume</strong>
          <span>Get a quality score and ATS compatibility estimate.</span>
        </Link>
        <Link className="quick-action" to="/match">
          <strong>Match to a job</strong>
          <span>See which requirements your resume evidences.</span>
        </Link>
        <Link className="quick-action" to="/rewrite">
          <strong>Rewrite with AI</strong>
          <span>Tailor wording without inventing anything.</span>
        </Link>
      </nav>

      <div className="dashboard-grid">
        <Panel
          id="dash-resumes"
          title="Resumes"
          resource={resumes}
          viewAll={{ to: '/resumes', label: 'All resumes' }}
          empty="No resumes yet. Upload one to see its analysis."
          emptyAction={
            <Link className="btn-small" to="/upload">
              Upload a resume
            </Link>
          }
        >
          {(items) => (
            <>
              {latest && <ResumeOverview latest={latest} count={resumes.state.data?.length ?? 0} />}
              {items.length > 1 && (
                <ul className="dash-list">
                  {items.slice(1).map((resume) => (
                    <li key={resume.id}>
                      <Link to={`/resumes/${resume.id}`}>{resume.filename}</Link>
                      <span className="report-meta">
                        {resume.overall_score != null ? `quality ${resume.overall_score}` : 'not scored'}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </Panel>

        <Panel
          id="dash-matches"
          title="Recent job matches"
          resource={matches}
          viewAll={{ to: '/matches', label: 'All matches' }}
          empty={hasResume ? 'No job matches yet.' : 'Upload a resume first, then match it to a job.'}
          emptyAction={
            hasResume && (
              <Link className="btn-small is-secondary" to="/match">
                Run a job match
              </Link>
            )
          }
        >
          {(items) => (
            <ul className="dash-list">
              {items.map((match) => (
                <li key={match.id}>
                  <Link to={`/matches/${match.id}`}>{match.job_title || 'Job description'}</Link>
                  <span
                    className="ledger-score"
                    style={{ '--seal-color': scoreColor(match.match_score) } as CSSProperties}
                  >
                    {match.match_score}% · {match.resume_filename}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel
          id="dash-jobs"
          title="Saved job descriptions"
          resource={jobs}
          viewAll={{ to: '/matches', label: 'All jobs' }}
          empty="No saved job descriptions. They are saved when you analyse one for a match or rewrite."
        >
          {(items) => (
            <ul className="dash-list">
              {items.map((job) => (
                <li key={job.id}>
                  <Link to={`/jobs/${job.id}`}>
                    {job.title || 'Untitled'}
                    {job.company ? ` · ${job.company}` : ''}
                  </Link>
                  <span className="report-meta">{plural(job.requirement_count, 'requirement')}</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel
          id="dash-rewrites"
          title="Recent rewrites"
          resource={rewrites}
          viewAll={{ to: '/rewrites', label: 'All rewrites' }}
          empty={hasResume ? 'No rewrites yet.' : 'Upload a resume first, then rewrite it.'}
          emptyAction={
            hasResume && (
              <Link className="btn-small is-secondary" to="/rewrite">
                Start a rewrite
              </Link>
            )
          }
        >
          {(items) => (
            <ul className="dash-list">
              {items.map((rewrite) => (
                <li key={rewrite.id}>
                  <Link to={`/rewrites/${rewrite.id}`}>{rewrite.name}</Link>
                  <span className="report-meta">
                    v{rewrite.current_version} · {formatDateTime(rewrite.updated_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        {/* Quick reviews are the original combined flow; the panel only appears for users who have some. */}
        {(reviews.state.status === 'error' || (reviews.state.data?.length ?? 0) > 0) && (
          <Panel
            id="dash-reviews"
            title="Quick reviews"
            resource={reviews}
            viewAll={{ to: '/reviews', label: 'All quick reviews' }}
            empty="No quick reviews."
          >
            {(items) => (
              <ul className="dash-list">
                {items.map((review) => (
                  <li key={review.id}>
                    <Link to={`/reviews/${review.id}`}>{review.resume_filename}</Link>
                    <span className="report-meta">
                      {review.score}/100 · {formatDateTime(review.created_at)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        )}
      </div>
      <p className="report-meta section-footnote">
        Prefer one step? <Link to="/reviews/new">Run a quick review</Link> of a resume against a job description.
      </p>
    </div>
  )
}
