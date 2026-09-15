import { useEffect, useState } from 'react'
import { fetchAnalyses, fetchAnalysis } from '../api/resume'

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

  if (status === 'loading') return <p>Loading history…</p>

  return (
    <div>
      <h2>Past Analyses</h2>

      {error && (
        <p style={{ color: 'red' }}>
          <strong>Error:</strong> {error}
        </p>
      )}

      {status === 'success' && items.length === 0 && <p>No past analyses yet.</p>}

      {items.length > 0 && (
        <ul style={{ listStyle: 'none', padding: 0 }}>
          {items.map((item) => (
            <li key={item.id} style={{ marginBottom: '0.5rem' }}>
              <button onClick={() => handleSelect(item.id)} disabled={loadingId === item.id}>
                {new Date(item.created_at).toLocaleString()} — {item.resume_filename} —{' '}
                {item.score}/100 ({item.score_label})
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
