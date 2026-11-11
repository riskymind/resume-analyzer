import type { CSSProperties } from 'react'
import type { MatchDetail, RequirementResult, SkillRef } from '../types/api'
import { scoreColor } from '../utils/score'
import ScoreSeal from './ui/ScoreSeal'

const STATUS: Record<RequirementResult['status'], { label: string; className: string }> = {
  matched: { label: 'Exact match', className: 'is-exact' },
  related: { label: 'Related, not equivalent', className: 'is-related' },
  partial: { label: 'Partly evidenced', className: 'is-related' },
  missing: { label: 'Not shown in resume', className: 'is-missing' },
}

function StatusChip({ status }: { status: RequirementResult['status'] }) {
  const meta = STATUS[status]
  return <span className={`status-chip ${meta.className}`}>{meta.label}</span>
}

function SkillChips({ items, empty, className }: { items: SkillRef[]; empty: string; className: string }) {
  if (items.length === 0) return <p className="none">{empty}</p>
  return (
    <p className="chip-row">
      {items.map((item) => (
        <span key={item.requirement_id} className={`chip ${className}`}>
          {item.name}
          {item.classification === 'preferred' && <small> · preferred</small>}
          {item.resume_term && <small> · you have {item.resume_term}</small>}
        </span>
      ))}
    </p>
  )
}

function RequirementRow({ result }: { result: RequirementResult }) {
  return (
    <li className={result.counted ? '' : 'is-uncounted'}>
      <details>
        <summary>
          <StatusChip status={result.status} />
          <span className="req-name">{result.name}</span>
          <span className={`req-badge ${result.classification === 'required' ? 'is-required' : 'is-preferred'}`}>
            {result.classification === 'required' ? 'Mandatory' : 'Preferred'}
          </span>
        </summary>
        <p>{result.explanation}</p>
        <p className="req-source">
          Job description: <q className="req-quote">{result.jd_evidence}</q>
        </p>
        {result.evidence.length > 0 && (
          <ul className="evidence-list" aria-label="Resume evidence">
            {result.evidence.map((evidence, index) => (
              <li key={index}>
                <small>
                  {evidence.section}
                  {evidence.label ? ` · ${evidence.label}` : ''}
                </small>
                <span>{evidence.text}</span>
              </li>
            ))}
          </ul>
        )}
      </details>
    </li>
  )
}

/** Deterministic job match report: score, breakdown, evidence for every requirement, grounded advice. */
export default function MatchReport({ match }: { match: MatchDetail }) {
  const report = match.report
  const mandatory = report.requirements.filter((r) => r.classification === 'required' && r.counted)
  const preferred = report.requirements.filter((r) => r.classification === 'preferred' && r.counted)
  const uncounted = report.requirements.filter((r) => !r.counted)
  const { skills, experience, qualifications, keywords, recommendations, semantic, confidence } = report

  return (
    <section className="match-report" aria-labelledby="match-title">
      <div className="report-head">
        <ScoreSeal score={report.match_score} unit="%" label="Job match" />
        <div className="report-head-text">
          <h2 id="match-title">{report.label}</h2>
          <p className="report-meta">
            {match.resume_filename} vs. {match.job_title || 'job description'}
          </p>
          <p className="quality-intro">{report.classification}</p>
        </div>
      </div>

      {report.score_cap && <p className="quality-note">{report.score_cap}</p>}
      {report.warnings.map((warning, index) => (
        <p key={index} className="quality-note">
          {warning}
        </p>
      ))}
      {semantic.status !== 'available' && (
        <p className="quality-note" role="note">
          <strong>Semantic matching was {semantic.status}.</strong> {semantic.reason} Matching used exact, alias and
          skill-family rules only, so experience described in different words may not be recognised, and confidence is
          lower.
        </p>
      )}
      <p className="report-meta">
        Confidence: <strong>{confidence.level}</strong> · {confidence.evidence_coverage}% of requirements have
        supporting evidence in the resume
      </p>
      {confidence.reasons.length > 0 && (
        <ul className="report-meta confidence-reasons">
          {confidence.reasons.map((reason, index) => (
            <li key={index}>{reason}</li>
          ))}
        </ul>
      )}

      {recommendations.top.length > 0 && (
        <div className="report-row">
          <h3>Most important improvements</h3>
          <ol className="fix-list">
            {recommendations.top.map((rec, index) => (
              <li key={index}>
                <span>{rec.message}</span>
                {rec.impact > 0 && <small>up to +{rec.impact} points</small>}
              </li>
            ))}
          </ol>
        </div>
      )}

      <div className="report-row">
        <h3>Skills</h3>
        <h4 className="sub-head">Exact matches</h4>
        <SkillChips items={skills.exact} empty="None" className="is-exact" />
        <h4 className="sub-head">Related skills (partial credit, not equivalent)</h4>
        <SkillChips items={skills.related} empty="None" className="is-related" />
        <h4 className="sub-head">Not shown in your resume</h4>
        <SkillChips items={skills.missing} empty="None" className="is-missing" />
      </div>

      <div className="report-row">
        <h3>Experience</h3>
        <ul>
          {experience.candidate_years != null && <li>About {experience.candidate_years} years across dated roles.</li>}
          {experience.required_years != null && <li>The job asks for {experience.required_years}+ years.</li>}
          <li>Seniority: {experience.seniority.explanation}</li>
          {experience.responsibility_alignment != null && (
            <li>Responsibility alignment: {experience.responsibility_alignment}/100.</li>
          )}
        </ul>
        {experience.gaps.length > 0 && (
          <>
            <h4 className="sub-head">Gaps</h4>
            <ul>
              {experience.gaps.map((gap, index) => (
                <li key={index}>{gap}</li>
              ))}
            </ul>
          </>
        )}
      </div>

      <div className="report-row">
        <h3>Qualifications</h3>
        <SkillChips
          items={[...qualifications.education_matched, ...qualifications.certifications_matched]}
          empty="No matching education or certifications were required or found."
          className="is-exact"
        />
        <SkillChips
          items={[...qualifications.education_missing, ...qualifications.certifications_missing]}
          empty="No qualification gaps."
          className="is-missing"
        />
      </div>

      <div className="report-row">
        <h3>Keywords {keywords.coverage != null && <small>· {keywords.coverage}% present</small>}</h3>
        <p className="chip-row">
          {keywords.present.map((term) => (
            <span key={term} className="chip is-exact">
              {term}
            </span>
          ))}
          {keywords.missing.map((term) => (
            <span key={term} className="chip is-missing">
              {term}
            </span>
          ))}
        </p>
      </div>

      {(
        [
          ['Mandatory requirements', mandatory],
          ['Preferred qualifications', preferred],
          ['Alternatives not scored separately', uncounted],
        ] as [string, RequirementResult[]][]
      )
        .filter(([, items]) => items.length > 0)
        .map(([title, items]) => (
          <div key={title} className="report-row">
            <h3>{title}</h3>
            <ul className="match-req-list">
              {items.map((result) => (
                <RequirementRow key={result.requirement_id} result={result} />
              ))}
            </ul>
          </div>
        ))}

      <div className="report-row">
        <h3>Score breakdown</h3>
        <ul className="dimension-list">
          {report.components
            .filter((component) => component.score != null)
            .map((component) => (
              <li key={component.key}>
                <div className="dimension-static">
                  <span className="dimension-name">{component.label}</span>
                  <span className="dimension-bar" aria-hidden="true">
                    <span
                      style={
                        {
                          width: `${component.score}%`,
                          background: scoreColor(component.score ?? 0),
                        } as CSSProperties
                      }
                    />
                  </span>
                  <span className="dimension-score">
                    {component.score}
                    <span className="visually-hidden"> out of 100</span>
                    <small> · {component.effective_weight}% weight</small>
                  </span>
                </div>
              </li>
            ))}
        </ul>
        <details className="methodology">
          <summary>How this score is calculated ({report.methodology.version})</summary>
          <p>{report.methodology.formula}</p>
          <ul>
            {report.methodology.notes.map((note, index) => (
              <li key={index}>{note}</li>
            ))}
          </ul>
        </details>
      </div>

      <p className="quality-disclaimer">{report.disclaimer}</p>
    </section>
  )
}
