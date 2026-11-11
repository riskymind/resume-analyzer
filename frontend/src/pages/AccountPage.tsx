import { useState } from 'react'
import { useAuth, useUser } from '../auth/AuthContext'
import DeleteAccountPanel from '../components/DeleteAccountPanel'
import PageHeader from '../components/ui/PageHeader'
import { formatDate } from '../utils/format'

export const ACCOUNT_DELETED_NOTICE = 'Your account and all of its data have been deleted.'

export default function AccountPage() {
  const user = useUser()
  const { signOut, signedOut } = useAuth()
  const [signingOut, setSigningOut] = useState(false)

  return (
    <div className="account-view">
      <PageHeader
        title="Account"
        meta={
          <p className="report-meta">
            Signed in as <strong>{user.email}</strong>
            {user.created_at && ` · member since ${formatDate(user.created_at)}`}
          </p>
        }
        actions={
          <button
            type="button"
            className="btn-small is-secondary"
            disabled={signingOut}
            onClick={() => {
              setSigningOut(true)
              void signOut()
            }}
          >
            {signingOut ? 'Signing out…' : 'Sign out'}
          </button>
        }
      />
      <DeleteAccountPanel email={user.email} onDeleted={() => signedOut(ACCOUNT_DELETED_NOTICE)} />
    </div>
  )
}
