const API_BASE_URL = 'http://localhost:8000/api'

async function handleJsonResponse(res) {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `Request failed with status ${res.status}`)
  }

  return res.json()
}

/**
 * Submits a resume file plus a job description (pasted text OR a file) for
 * analysis. Exactly one of jdText/jdFile should be provided.
 */
export async function analyzeResume({ resumeFile, jdText, jdFile }) {
  const formData = new FormData()
  formData.append('resume', resumeFile)

  if (jdFile) {
    formData.append('jd_file', jdFile)
  } else {
    formData.append('jd_text', jdText ?? '')
  }

  const res = await fetch(`${API_BASE_URL}/analyze`, {
    method: 'POST',
    body: formData,
  })

  return handleJsonResponse(res)
}

/** Fetches the list of past analyses, most recent first. */
export async function fetchAnalyses() {
  const res = await fetch(`${API_BASE_URL}/analyses`)
  return handleJsonResponse(res)
}

/** Fetches one past analysis by id, without re-calling the LLM. */
export async function fetchAnalysis(id) {
  const res = await fetch(`${API_BASE_URL}/analyses/${id}`)
  return handleJsonResponse(res)
}
