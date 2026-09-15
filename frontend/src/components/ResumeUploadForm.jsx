import { useState } from 'react'
import { analyzeResume } from '../api/resume'

const ALLOWED_EXTENSIONS = ['.pdf', '.md']
const MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024 // 5 MB

function validateFile(file, label) {
  if (!file) {
    return `Please select a ${label.toLowerCase()} file.`
  }

  const name = file.name.toLowerCase()
  if (!ALLOWED_EXTENSIONS.some((ext) => name.endsWith(ext))) {
    return `${label} must be a .pdf or .md file.`
  }
  if (file.size > MAX_FILE_SIZE_BYTES) {
    return `${label} must be smaller than 5MB.`
  }
  return null
}

/**
 * Upload form for a resume file plus a job description, entered either as
 * pasted text or as its own .pdf/.md file. Submits directly to the analyze
 * endpoint and hands the resulting record back via onAnalyzed.
 */
export default function ResumeUploadForm({ onAnalyzed }) {
  const [resumeFile, setResumeFile] = useState(null)
  const [jdMode, setJdMode] = useState('text') // 'text' | 'file'
  const [jdText, setJdText] = useState('')
  const [jdFile, setJdFile] = useState(null)
  const [status, setStatus] = useState('idle') // idle | submitting
  const [error, setError] = useState(null)

  async function handleSubmit(event) {
    event.preventDefault()
    setError(null)

    const resumeError = validateFile(resumeFile, 'Resume')
    if (resumeError) {
      setError(resumeError)
      return
    }

    if (jdMode === 'text') {
      if (!jdText.trim()) {
        setError('Please paste a job description, or switch to file upload.')
        return
      }
    } else {
      const jdFileError = validateFile(jdFile, 'Job description file')
      if (jdFileError) {
        setError(jdFileError)
        return
      }
    }

    setStatus('submitting')
    try {
      const record = await analyzeResume({
        resumeFile,
        jdText: jdMode === 'text' ? jdText : undefined,
        jdFile: jdMode === 'file' ? jdFile : undefined,
      })
      onAnalyzed(record)
    } catch (err) {
      setError(err.message)
    } finally {
      setStatus('idle')
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <div style={{ marginBottom: '1rem' }}>
        <label htmlFor="resume-file">
          <strong>Resume</strong> (.pdf or .md)
        </label>
        <br />
        <input
          id="resume-file"
          type="file"
          accept=".pdf,.md"
          onChange={(e) => setResumeFile(e.target.files[0] ?? null)}
        />
      </div>

      <div style={{ marginBottom: '1rem' }}>
        <strong>Job description</strong>
        <br />
        <label style={{ marginRight: '1rem' }}>
          <input
            type="radio"
            name="jd-mode"
            checked={jdMode === 'text'}
            onChange={() => setJdMode('text')}
          />{' '}
          Paste text
        </label>
        <label>
          <input
            type="radio"
            name="jd-mode"
            checked={jdMode === 'file'}
            onChange={() => setJdMode('file')}
          />{' '}
          Upload file
        </label>
        <br />

        {jdMode === 'text' ? (
          <textarea
            rows={8}
            style={{ width: '100%', marginTop: '0.5rem' }}
            placeholder="Paste the job description here…"
            value={jdText}
            onChange={(e) => setJdText(e.target.value)}
          />
        ) : (
          <input
            type="file"
            accept=".pdf,.md"
            style={{ marginTop: '0.5rem' }}
            onChange={(e) => setJdFile(e.target.files[0] ?? null)}
          />
        )}
      </div>

      {error && (
        <p style={{ color: 'red' }}>
          <strong>Error:</strong> {error}
        </p>
      )}

      <button type="submit" disabled={status === 'submitting'}>
        {status === 'submitting' ? 'Analyzing…' : 'Analyze'}
      </button>
    </form>
  )
}
