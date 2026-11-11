import { useId, useState, type FormEvent } from 'react'
import { analyzeResume } from '../api/resume'
import type { AnalysisRecord } from '../types/api'
import { validateFile } from '../utils/files'
import { Flag } from './ui/Feedback'
import Tabs from './ui/Tabs'

type JdMode = 'text' | 'file'

/**
 * Quick review: a resume file plus a job description, entered either as pasted text or as its own .pdf/.docx/.md
 * file. Submits to the analyze endpoint and hands the resulting record back via onAnalyzed.
 */
export default function ResumeUploadForm({ onAnalyzed }: { onAnalyzed: (record: AnalysisRecord) => void }) {
  const [resumeFile, setResumeFile] = useState<File | null>(null)
  const [jdMode, setJdMode] = useState<JdMode>('text')
  const [jdText, setJdText] = useState('')
  const [jdFile, setJdFile] = useState<File | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const resumeInputId = useId()
  const jdInputId = useId()
  const jdTextId = useId()

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)

    const resumeError = validateFile(resumeFile, 'Resume')
    if (resumeError || !resumeFile) return setError(resumeError)

    if (jdMode === 'text') {
      if (!jdText.trim()) return setError('Paste a job description, or switch to file upload.')
    } else {
      const jdFileError = validateFile(jdFile, 'Job description file')
      if (jdFileError) return setError(jdFileError)
    }

    setSubmitting(true)
    try {
      const record = await analyzeResume({
        resumeFile,
        jdText: jdMode === 'text' ? jdText : undefined,
        jdFile: jdMode === 'file' && jdFile ? jdFile : undefined,
      })
      onAnalyzed(record)
    } catch (err) {
      setError((err as Error).message)
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate>
      <div className="document-grid">
        <div className="document-panel">
          <h2 className="panel-title">Resume</h2>
          <p className="panel-hint">.pdf, .docx or .md, up to 5MB</p>
          <div className={`file-drop ${resumeFile ? 'has-file' : ''}`}>
            <input
              id={resumeInputId}
              type="file"
              accept=".pdf,.docx,.md"
              onChange={(e) => setResumeFile(e.target.files?.[0] ?? null)}
            />
            <label htmlFor={resumeInputId}>{resumeFile ? resumeFile.name : 'Choose file…'}</label>
          </div>
        </div>

        <div className="document-panel">
          <h2 className="panel-title">Job description</h2>
          <p className="panel-hint">Paste it in, or attach the posting</p>
          <Tabs<JdMode>
            label="Job description source"
            items={[
              { key: 'text', label: 'Paste text' },
              { key: 'file', label: 'Upload file' },
            ]}
            value={jdMode}
            onChange={setJdMode}
          >
            {jdMode === 'text' ? (
              <>
                <label htmlFor={jdTextId} className="visually-hidden">
                  Job description text
                </label>
                <textarea
                  id={jdTextId}
                  className="jd-textarea"
                  rows={6}
                  placeholder="Paste the job description here…"
                  value={jdText}
                  onChange={(e) => setJdText(e.target.value)}
                />
              </>
            ) : (
              <div className={`file-drop ${jdFile ? 'has-file' : ''}`}>
                <input
                  id={jdInputId}
                  type="file"
                  accept=".pdf,.docx,.md"
                  onChange={(e) => setJdFile(e.target.files?.[0] ?? null)}
                />
                <label htmlFor={jdInputId}>{jdFile ? jdFile.name : 'Choose file…'}</label>
              </div>
            )}
          </Tabs>
        </div>
      </div>

      <Flag message={error} />
      {submitting && (
        <p className="empty-note" role="status">
          Reviewing your resume against the job… this can take up to a minute.
        </p>
      )}

      <div className="submit-row">
        <button className="btn-primary" type="submit" disabled={submitting}>
          {submitting ? 'Reviewing…' : 'Review resume'}
        </button>
      </div>
    </form>
  )
}
