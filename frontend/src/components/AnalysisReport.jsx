const CATEGORY_LABELS = {
  missing_keywords: 'Missing Keywords',
  phrasing_suggestions: 'Phrasing Suggestions',
  skill_gaps: 'Skill Gaps',
  formatting_notes: 'Formatting Notes',
}

/** Renders a fitment score and its recommendation categories for one analysis record. */
export default function AnalysisReport({ record }) {
  const { result, resume_filename: resumeFilename, jd_source: jdSource, created_at: createdAt } = record

  return (
    <section>
      <h2>Analysis Report</h2>
      <p>
        <strong>{resumeFilename}</strong> vs. job description (
        {jdSource === 'pasted' ? 'pasted text' : jdSource})
        {createdAt && <> — {new Date(createdAt).toLocaleString()}</>}
      </p>

      <p>
        <span style={{ fontSize: '2rem', fontWeight: 'bold' }}>{result.score}</span>
        <span>/100 — {result.score_label}</span>
      </p>

      {Object.entries(CATEGORY_LABELS).map(([key, label]) => {
        const items = result.recommendations[key] ?? []
        return (
          <div key={key} style={{ marginBottom: '1rem' }}>
            <h3>{label}</h3>
            {items.length > 0 ? (
              <ul>
                {items.map((item, index) => (
                  <li key={index}>{item}</li>
                ))}
              </ul>
            ) : (
              <p>None</p>
            )}
          </div>
        )
      })}
    </section>
  )
}
