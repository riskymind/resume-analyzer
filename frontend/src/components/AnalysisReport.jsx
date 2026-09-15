const CATEGORY_LABELS = {
  missing_keywords: 'Missing keywords',
  phrasing_suggestions: 'Phrasing suggestions',
  skill_gaps: 'Skill gaps',
  formatting_notes: 'Formatting notes',
}

/** Score-tier color, matched to the token palette in index.css. */
function sealColor(score) {
  if (score >= 80) return 'var(--accent-teal)'
  if (score >= 50) return 'var(--accent-ochre)'
  return 'var(--accent-brick)'
}

/** Renders a fitment score and its recommendation categories for one analysis record. */
export default function AnalysisReport({ record }) {
  const { result, resume_filename: resumeFilename, jd_source: jdSource, created_at: createdAt } = record

  return (
    <section>
      <div className="report-head">
        <div className="score-seal" style={{ '--seal-color': sealColor(result.score) }}>
          <span className="score-value">{result.score}</span>
          <span className="score-max">/ 100</span>
        </div>
        <div className="report-head-text">
          <h2>{result.score_label}</h2>
          <p className="report-meta">
            {resumeFilename} vs. {jdSource === 'pasted' ? 'pasted job description' : jdSource}
          </p>
        </div>
      </div>

      {createdAt && <p className="report-source">Reviewed {new Date(createdAt).toLocaleString()}</p>}

      {Object.entries(CATEGORY_LABELS).map(([key, label]) => {
        const items = result.recommendations[key] ?? []
        return (
          <div key={key} className="report-row">
            <h3>{label}</h3>
            {items.length > 0 ? (
              <ul>
                {items.map((item, index) => (
                  <li key={index}>{item}</li>
                ))}
              </ul>
            ) : (
              <p className="none">None</p>
            )}
          </div>
        )
      })}
    </section>
  )
}
