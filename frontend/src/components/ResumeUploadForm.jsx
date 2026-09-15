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
        setError('Paste a job description, or switch to file upload.')
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
      <p className="intake-intro">
        Bring your resume and the job posting. We'll mark it up like an editor would.
      </p>

      <div className="document-grid">
        <div className="document-panel">
          <h3>Resume</h3>
          <p className="panel-hint">.pdf or .md, up to 5MB</p>
          <label className={`file-drop ${resumeFile ? 'has-file' : ''}`}>
            <input
              type="file"
              accept=".pdf,.md"
              onChange={(e) => setResumeFile(e.target.files[0] ?? null)}
            />
            {resumeFile ? resumeFile.name : 'Choose file…'}
          </label>
        </div>

        <div className="document-panel">
          <h3>Job description</h3>
          <p className="panel-hint">Paste it in, or attach the posting</p>
          <div className="mode-tabs">
            <button
              type="button"
              className={jdMode === 'text' ? 'is-active' : ''}
              onClick={() => setJdMode('text')}
            >
              Paste text
            </button>
            <button
              type="button"
              className={jdMode === 'file' ? 'is-active' : ''}
              onClick={() => setJdMode('file')}
            >
              Upload file
            </button>
          </div>

          {jdMode === 'text' ? (
            <textarea
              className="jd-textarea"
              rows={6}
              placeholder="Paste the job description here…"
              value={jdText}
              onChange={(e) => setJdText(e.target.value)}
            />
          ) : (
            <label className={`file-drop ${jdFile ? 'has-file' : ''}`}>
              <input
                type="file"
                accept=".pdf,.md"
                onChange={(e) => setJdFile(e.target.files[0] ?? null)}
              />
              {jdFile ? jdFile.name : 'Choose file…'}
            </label>
          )}
        </div>
      </div>

      {error && (
        <p className="form-flag">
          <span>{error}</span>
        </p>
      )}

      <div className="submit-row">
        <button className="btn-primary" type="submit" disabled={status === 'submitting'}>
          {status === 'submitting' ? 'Reviewing…' : 'Review resume'}
        </button>
      </div>
    </form>
  )
}
