import type { CSSProperties } from 'react'
import type { QualityReport as QualityReportData, ResumeDetail } from '../types/api'
import { scoreColor } from '../utils/score'
import ExtractedResume from './ExtractedResume'
import ScoreSeal from './ui/ScoreSeal'

function List({ items, empty = 'None' }: { items: string[]; empty?: string }) {
  if (items.length === 0) return <p className="none">{empty}</p>
  return (
    <ul>
      {items.map((item, index) => (
        <li key={index}>{item}</li>
      ))}
    </ul>
  )
}

/**
 * Job-independent resume quality: overall and ATS scores and an explainable per-dimension breakdown. Every number
 * comes from the API's deterministic scorer; this component only presents them.
 */
export default function QualityReport({
  quality,
  resumeId,
  resume,
}: {
  quality: QualityReportData
  resumeId?: string | null
  /** The already-loaded resume, so the extraction panel does not fetch it again. */
  resume?: ResumeDetail | null
}) {
  const failedChecks = quality.ats_checks.filter((check) => !check.passed)
  const topRecommendations = quality.recommendations.slice(0, 5)

  return (
    <section className="quality" aria-labelledby="quality-title">
      <h2 id="quality-title" className="quality-title">
        Resume quality
      </h2>
      <p className="quality-intro">
        Scored by fixed rules on the resume alone, so it does not change with the job you target. For how well it fits a
        specific job, run a job match.
      </p>

      <div className="quality-scores">
        <ScoreSeal score={quality.overall_score} label="Resume quality" />
        <div>
          <p className="quality-label">{quality.label}</p>
          <p className="report-meta">
            ATS compatibility estimate <strong>{quality.ats_score}/100</strong>
          </p>
        </div>
      </div>
      <p className="ats-disclaimer" role="note">
        {quality.disclaimer}
      </p>

      {quality.score_cap && <p className="quality-note">{quality.score_cap}</p>}

      {topRecommendations.length > 0 && (
        <div className="report-row">
          <h3>Most valuable fixes</h3>
          <ol className="fix-list">
            {topRecommendations.map((rec, index) => (
              <li key={index}>
                <span>{rec.recommendation}</span>
                <small>
                  {rec.message} · up to +{rec.impact} points
                </small>
              </li>
            ))}
          </ol>
        </div>
      )}

      <div className="report-row">
        <h3>Score breakdown</h3>
        <ul className="dimension-list">
          {quality.dimensions.map((dimension) => (
            <li key={dimension.key}>
              <details>
                <summary>
                  <span className="dimension-name">{dimension.label}</span>
                  <span className="dimension-bar" aria-hidden="true">
                    <span
                      style={{ width: `${dimension.score}%`, background: scoreColor(dimension.score) } as CSSProperties}
                    />
                  </span>
                  <span className="dimension-score">
                    {dimension.score}
                    <span className="visually-hidden"> out of 100</span>
                    <small> · {dimension.weight}% weight</small>
                  </span>
                </summary>
                {dimension.deductions.length === 0 && dimension.strengths.length === 0 && (
                  <p className="none">No issues found.</p>
                )}
                {dimension.deductions.length > 0 && (
                  <ul className="deductions">
                    {dimension.deductions.map((deduction) => (
                      <li key={deduction.code}>
                        <span className="deduction-points">
                          <span aria-hidden="true">−</span>
                          <span className="visually-hidden">minus </span>
                          {deduction.points}
                        </span>
                        <span>
                          {deduction.message} <em>{deduction.recommendation}</em>
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
                {dimension.strengths.length > 0 && (
                  <ul className="strengths">
                    {dimension.strengths.map((strength, index) => (
                      <li key={index}>{strength}</li>
                    ))}
                  </ul>
                )}
              </details>
            </li>
          ))}
        </ul>
      </div>

      <div className="report-row">
        <h3>Strengths</h3>
        <List items={quality.strengths} />
      </div>

      <div className="report-row">
        <h3>Weaknesses</h3>
        <List items={quality.weaknesses} />
      </div>

      <div className="report-row">
        <h3>Missing information</h3>
        <List items={quality.missing_information} />
      </div>

      {failedChecks.length > 0 && (
        <div className="report-row">
          <h3>ATS readability</h3>
          <ul>
            {failedChecks.map((check) => (
              <li key={check.code}>
                {check.message} {check.recommendation && <em>{check.recommendation}</em>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {resumeId && <ExtractedResume resumeId={resumeId} resume={resume} />}
    </section>
  )
}
