import type { JobDetail, JobRequirement } from '../types/api'

const CATEGORY_LABELS: Record<JobRequirement['category'], string> = {
  technical_skill: 'Technical skills',
  soft_skill: 'Soft skills',
  experience: 'Experience',
  education: 'Education',
  certification: 'Certifications',
  responsibility: 'Responsibilities',
}

/** Requirements extracted from a job description, each with the verbatim text that supports it. */
export default function JobRequirements({ job }: { job: JobDetail }) {
  const groups = (Object.keys(CATEGORY_LABELS) as JobRequirement['category'][])
    .map((category) => [category, job.requirements.filter((r) => r.category === category)] as const)
    .filter(([, items]) => items.length > 0)
  const info = job.info
  const facts: [string, string | null][] = [
    ['Company', info.company?.value],
    ['Location', info.location?.value],
    ['Arrangement', info.work_arrangement?.value],
    ['Type', info.employment_type?.value],
    ['Seniority', info.seniority?.value],
  ]
  const shown = facts.filter((fact): fact is [string, string] => Boolean(fact[1]))

  return (
    <section className="job-requirements" aria-labelledby="job-req-title">
      <h2 id="job-req-title" className="section-title">
        {job.title || 'Untitled job description'}
      </h2>
      {shown.length > 0 && (
        <p className="report-meta">{shown.map(([label, value]) => `${label}: ${value}`).join(' · ')}</p>
      )}
      {job.warnings.map((warning, index) => (
        <p key={index} className="quality-note">
          {warning}
        </p>
      ))}
      <p className="report-meta">
        These requirements were extracted from the job description and checked against its text; anything that could not
        be found there was discarded.
      </p>
      <p className="req-legend">
        <span className="req-badge is-required">Mandatory</span>
        <span className="req-badge is-preferred">Preferred</span>
        Each item quotes the job description it came from.
      </p>
      {groups.map(([category, items]) => (
        <div key={category} className="report-row">
          <h3>{CATEGORY_LABELS[category]}</h3>
          <ul className="req-list">
            {items.map((req) => (
              <li key={req.id}>
                <span className={`req-badge ${req.classification === 'required' ? 'is-required' : 'is-preferred'}`}>
                  {req.classification === 'required' ? 'Mandatory' : 'Preferred'}
                </span>
                <span className="req-name">
                  {req.name}
                  {req.min_years ? ` (${req.min_years}+ yrs)` : ''}
                  {req.alternative_group && <small className="req-alt"> · one of a set of alternatives</small>}
                </span>
                <q className="req-quote">{req.evidence}</q>
              </li>
            ))}
          </ul>
        </div>
      ))}
      {job.keywords.length > 0 && (
        <div className="report-row">
          <h3>Keywords</h3>
          <p className="chip-row">
            {job.keywords.map((keyword) => (
              <span key={keyword.term} className="chip">
                {keyword.term}
              </span>
            ))}
          </p>
        </div>
      )}
    </section>
  )
}
