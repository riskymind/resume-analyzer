import { useState, type SyntheticEvent } from 'react'
import { fetchResume } from '../api/resume'
import type { ResumeDetail, TextField } from '../types/api'

function Value({ field }: { field: TextField | null | undefined }) {
  if (!field || field.status === 'missing' || !field.value) return <span className="field-missing">not found</span>
  return (
    <>
      {field.value}
      {field.status === 'inferred' && (
        <span className="field-tag" title={field.evidence ? `Based on: “${field.evidence}”` : undefined}>
          inferred
        </span>
      )}
    </>
  )
}

function dates(entry: { start_date: TextField; end_date: TextField }): string | null {
  const start = entry.start_date?.value
  const end = entry.end_date?.value
  if (!start && !end) return null
  return `${start ?? '?'} – ${end ?? '?'}`
}

/**
 * What the app extracted from the resume. Loaded on demand. Every value was
 * checked against the resume text; "inferred" marks the few fields derived
 * from a quoted sentence rather than stated outright.
 */
type LoadState =
  | { status: 'idle' | 'loading'; resume: null; error: null }
  | { status: 'success'; resume: ResumeDetail; error: null }
  | { status: 'error'; resume: null; error: string }

export default function ExtractedResume({ resumeId, resume }: { resumeId: string; resume?: ResumeDetail | null }) {
  // When the page already loaded the resume, use it instead of fetching it again.
  const [state, setState] = useState<LoadState>(
    resume ? { status: 'success', resume, error: null } : { status: 'idle', resume: null, error: null },
  )

  async function load(event: SyntheticEvent<HTMLDetailsElement>) {
    if (!event.currentTarget.open || state.status !== 'idle') return
    setState({ status: 'loading', resume: null, error: null })
    try {
      setState({ status: 'success', resume: await fetchResume(resumeId), error: null })
    } catch (err) {
      setState({ status: 'error', resume: null, error: (err as Error).message })
    }
  }

  const structured = state.resume?.structured

  return (
    <details className="extracted" onToggle={load}>
      <summary>What we extracted from your resume</summary>
      {state.status === 'loading' && (
        <p className="empty-note" role="status">
          Loading…
        </p>
      )}
      {state.status === 'error' && (
        <p className="form-flag" role="alert">
          <span>{state.error}</span>
        </p>
      )}
      {structured && state.resume && (
        <div className="extracted-body">
          {state.resume.warnings.map((warning, index) => (
            <p key={index} className="quality-note">
              {warning}
            </p>
          ))}
          <dl>
            <dt>Name</dt>
            <dd>
              <Value field={structured.contact.name} />
            </dd>
            <dt>Email</dt>
            <dd>
              <Value field={structured.contact.email} />
            </dd>
            <dt>Phone</dt>
            <dd>
              <Value field={structured.contact.phone} />
            </dd>
            <dt>Location</dt>
            <dd>
              <Value field={structured.contact.location} />
            </dd>
          </dl>

          <h4>Experience</h4>
          {structured.experience.length === 0 ? (
            <p className="none">None found</p>
          ) : (
            <ul>
              {structured.experience.map((entry, index) => (
                <li key={index}>
                  <strong>
                    <Value field={entry.title} />
                  </strong>{' '}
                  at <Value field={entry.employer} />
                  {dates(entry) && <span className="report-meta"> · {dates(entry)}</span>}
                  <span className="report-meta">
                    {' '}
                    · {entry.achievements.length} achievement(s), {entry.responsibilities.length} responsibility
                    bullet(s)
                  </span>
                </li>
              ))}
            </ul>
          )}

          <h4>Education</h4>
          {structured.education.length === 0 ? (
            <p className="none">None found</p>
          ) : (
            <ul>
              {structured.education.map((entry, index) => (
                <li key={index}>
                  <Value field={entry.qualification} />, <Value field={entry.institution} />
                </li>
              ))}
            </ul>
          )}

          <h4>Skills</h4>
          <p>
            {structured.technical_skills.map((skill) => skill.name).join(', ') || (
              <span className="field-missing">none found</span>
            )}
          </p>
          {structured.soft_skills.length > 0 && (
            <p>
              {structured.soft_skills.map((skill) => (
                <span key={skill.name} className="soft-skill">
                  {skill.name}
                  {skill.status === 'inferred' && (
                    <span className="field-tag" title={skill.evidence ? `Based on: “${skill.evidence}”` : undefined}>
                      inferred
                    </span>
                  )}
                </span>
              ))}
            </p>
          )}

          {(structured.certifications.length > 0 ||
            structured.projects.length > 0 ||
            structured.languages.length > 0) && (
            <>
              <h4>Other</h4>
              <ul>
                {structured.certifications.map((cert, index) => (
                  <li key={`c${index}`}>
                    Certification: <Value field={cert.name} />
                  </li>
                ))}
                {structured.projects.map((project, index) => (
                  <li key={`p${index}`}>
                    Project: <Value field={project.name} />
                  </li>
                ))}
                {structured.languages.map((language) => (
                  <li key={language.name}>
                    Language: {language.name}
                    {language.proficiency?.value && <> ({language.proficiency.value})</>}
                  </li>
                ))}
              </ul>
            </>
          )}

          {structured.extraction.removed_items > 0 && (
            <p className="report-meta">
              {structured.extraction.removed_items} item(s) suggested by the AI were discarded because they do not
              appear in your resume.
            </p>
          )}
        </div>
      )}
    </details>
  )
}
