import { useState } from 'react'
import { pingGemini } from '../api/gemini'

export default function PingGeminiButton() {
  const [status, setStatus] = useState('idle') // idle | loading | success | error
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  async function handleClick() {
    setStatus('loading')
    setError(null)

    try {
      const data = await pingGemini()
      setResult(data)
      setStatus('success')
    } catch (err) {
      setError(err.message)
      setStatus('error')
    }
  }

  return (
    <div>
      <button onClick={handleClick} disabled={status === 'loading'}>
        {status === 'loading' ? 'Pinging Gemini…' : 'Ping Gemini'}
      </button>

      {status === 'success' && result && (
        <p>
          <strong>Gemini says:</strong> {result.response}
        </p>
      )}

      {status === 'error' && (
        <p style={{ color: 'red' }}>
          <strong>Error:</strong> {error}
        </p>
      )}
    </div>
  )
}
