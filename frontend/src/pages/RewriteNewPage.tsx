import { Link, useNavigate, useSearchParams } from 'react-router'
import { fetchJob, fetchJobs } from '../api/jobs'
import { fetchResumes } from '../api/resume'
import RewriteSetup from '../components/rewrite/RewriteSetup'
import { ErrorState, Loading } from '../components/ui/Feedback'
import PageHeader from '../components/ui/PageHeader'
import { useResource } from '../hooks/useResource'
import type { JobDetail } from '../types/api'

/**
 * Start an AI rewrite. `?resume=` and `?job=` preselect a saved resume and target job. The new rewrite opens in
 * its workspace at /rewrites/:id.
 */
export default function RewriteNewPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const initialResumeId = params.get('resume')
  const initialJobId = params.get('job')
  const resumes = useResource('resumes', fetchResumes)
  const jobs = useResource('jobs', fetchJobs)
  const initialJob = useResource<JobDetail | null>(initialJobId ? `job:${initialJobId}` : 'no-job', () =>
    initialJobId ? fetchJob(initialJobId) : Promise.resolve(null),
  )

  return (
    <div className="rewrite-page">
      <PageHeader
        title="Rewrite your resume"
        meta={
          <p className="intake-intro">
            Rewrite your resume with AI, without inventing anything. Every change is checked against your original
            resume before you see it.
          </p>
        }
        actions={
          <Link className="btn-small is-secondary" to="/rewrites">
            Saved rewrites
          </Link>
        }
      />

      {resumes.state.status === 'error' && <ErrorState error={resumes.state.error} onRetry={resumes.reload} />}
      {jobs.state.status === 'error' && <ErrorState error={jobs.state.error} onRetry={jobs.reload} />}
      {initialJob.state.status === 'error' && (
        <ErrorState
          error={initialJob.state.error}
          onRetry={initialJob.reload}
          resource="job description"
          back={{ to: '/rewrite', label: 'Start without it' }}
        />
      )}
      {initialJob.state.status === 'loading' ? (
        <Loading>Loading the job description…</Loading>
      ) : (
        initialJob.state.status === 'success' && (
          <RewriteSetup
            resumes={resumes.state.data ?? []}
            jobs={jobs.state.data ?? []}
            initialResumeId={initialResumeId}
            initialJob={initialJob.state.data}
            onResumeUploaded={(resume) => resumes.setData([resume, ...(resumes.state.data ?? [])])}
            onJobsChanged={jobs.reload}
            onCreated={(rewrite) => navigate(`/rewrites/${rewrite.id}`)}
          />
        )
      )}
    </div>
  )
}
