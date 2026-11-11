import { Link, useLocation } from 'react-router'
import PageHeader from '../components/ui/PageHeader'

export default function NotFoundPage() {
  const { pathname } = useLocation()
  return (
    <div className="not-found">
      <PageHeader title="Page not found" />
      <p className="report-meta">
        There is no page at <code>{pathname}</code>. The link may be mistyped, or the page may have moved.
      </p>
      <p className="not-found-links">
        <Link to="/">Go to the dashboard</Link>
      </p>
    </div>
  )
}
