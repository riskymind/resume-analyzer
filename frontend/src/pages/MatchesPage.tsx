import { Link } from 'react-router'
import SavedMatches from '../components/SavedMatches'
import PageHeader from '../components/ui/PageHeader'

export default function MatchesPage() {
  return (
    <div>
      <PageHeader
        title="Saved matches and jobs"
        actions={
          <Link className="btn-small" to="/match">
            New match
          </Link>
        }
      />
      <SavedMatches />
    </div>
  )
}
