const API_BASE_URL = 'http://localhost:8000/api'

/**
 * Calls the backend smoke-test endpoint, which sends a hardcoded prompt to
 * Gemini and returns its response. Confirms frontend -> backend -> Gemini
 * wiring end to end.
 */
export async function pingGemini() {
  const res = await fetch(`${API_BASE_URL}/ping-gemini`)

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `Request failed with status ${res.status}`)
  }

  return res.json()
}
