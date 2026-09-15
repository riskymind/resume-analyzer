import { useEffect, useState } from 'react'
import { fetchAnalyses, fetchAnalysis } from '../api/resume'

/** Score-tier color, matched to the token palette in index.css. */
function sealColor(score) {
  if (score >= 80) return 'var(--accent-teal)'
  if (score >= 50) return 'var(--accent-ochre)'
  return 'var(--accent-brick)'
}

/** Lists past analyses; selecting one fetches its full record via onSelect. */
export default function HistoryList({ onSelect }) {
  const [status, setStatus] = useState('loading') // loading | success | error
  const [items, setItems] = useState([])
  const [error, setError] = useState(null)
  const [loadingId, setLoadingId] = useState(null)

  useEffect(() => {
    let cancelled = false

    fetchAnalyses()
      .then((data) => {
        if (!cancelled) {
          setItems(data)
          setStatus('success')
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err.message)
          setStatus('error')
        }
      })

    return () => {
      cancelled = true
    }
  }, [])

  async function handleSelect(id) {
    setLoadingId(id)
    setError(null)
    try {
      const record = await fetchAnalysis(id)
      onSelect(record)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoadingId(null)
    }
  }

  if (status === 'loading') return <p className="empty-note">Loading history…</p>

  return (
    <div>
      <h2 className="ledger-title">Past reviews</h2>

      {error && (
        <p className="form-flag">
          <span>{error}</span>
        </p>
      )}

      {status === 'success' && items.length === 0 && (
        <p className="empty-note">No reviews yet. Run your first one to see it here.</p>
      )}

      {items.length > 0 && (
        <div className="ledger">
          {items.map((item) => (
            <button
              key={item.id}
              className="ledger-row"
              onClick={() => handleSelect(item.id)}
              disabled={loadingId === item.id}
            >
              <span className="ledger-filename">{item.resume_filename}</span>
              <span className="ledger-date">{new Date(item.created_at).toLocaleString()}</span>
              <span className="ledger-score" style={{ '--seal-color': sealColor(item.score) }}>
                {item.score}/100 — {item.score_label}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
