import { Link, useNavigate } from 'react-router'
import ResumeUploadForm from '../components/ResumeUploadForm'
import PageHeader from '../components/ui/PageHeader'

/** Quick review: upload a resume and a job description in one step (the original flow, kept unchanged). */
export default function ReviewNewPage() {
  const navigate = useNavigate()
  return (
    <div>
      <PageHeader
        title="Quick review"
        meta={
          <p className="intake-intro">Bring your resume and the job posting. We'll mark it up like an editor would.</p>
        }
        actions={
          <Link className="btn-small is-secondary" to="/reviews">
            Past quick reviews
          </Link>
        }
      />
      <ResumeUploadForm onAnalyzed={(record) => navigate(`/reviews/${record.id}`)} />
    </div>
  )
}
