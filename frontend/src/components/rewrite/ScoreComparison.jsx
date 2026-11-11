import { scoreColor } from '../../utils/score'

function Delta({ before, after }) {
  const change = after - before
  const label = change > 0 ? `+${change}` : `${change}`
  return (
    <span className={`score-delta ${change > 0 ? 'is-up' : change < 0 ? 'is-down' : ''}`}>
      {change === 0 ? '±0' : label}
    </span>
  )
}

function Pair({ title, before, after, beforeLabel, afterLabel, note }) {
  return (
    <div className="score-pair">
      <h3>{title}</h3>
      <div className="score-pair-row">
        <div className="score-mini" style={{ '--seal-color': scoreColor(before) }} aria-label={`Before: ${before}`}>
          <span className="score-value">{before}</span>
          <span className="score-max">before</span>
        </div>
        <span className="score-arrow" aria-hidden="true">
          →
        </span>
        <div className="score-mini" style={{ '--seal-color': scoreColor(after) }} aria-label={`After: ${after}`}>
          <span className="score-value">{after}</span>
          <span className="score-max">after</span>
        </div>
        <Delta before={before} after={after} />
      </div>
      {(beforeLabel || afterLabel) && (
        <p className="report-meta">
          {beforeLabel} → {afterLabel}
        </p>
      )}
      {note && <p className="score-note">{note}</p>}
    </div>
  )
}

/** Before/after scores recalculated by the deterministic engines from the saved content. */
export default function ScoreComparison({ scores }) {
  const { quality, match } = scores
  return (
    <section className="rewrite-panel" aria-labelledby="scores-title">
      <h2 id="scores-title">Before and after</h2>
      <div className="score-pairs">
        <Pair
          title="Resume quality"
          before={quality.before}
          after={quality.after}
          beforeLabel={quality.before_label}
          afterLabel={quality.after_label}
          note={quality.uploaded_score != null ? `Uploaded file scored ${quality.uploaded_score}.` : null}
        />
        <Pair title="ATS readability" before={quality.before_ats} after={quality.after_ats} />
        {match && (
          <Pair
            title="Job match"
            before={match.before}
            after={match.after}
            beforeLabel={match.before_label}
            afterLabel={match.after_label}
            note={match.saved_match_score != null ? `Saved match report: ${match.saved_match_score}%.` : null}
          />
        )}
      </div>
      {scores.keywords_incorporated.length > 0 && (
        <>
          <p className="sub-head">Job keywords now included</p>
          <div className="chip-row">
            {scores.keywords_incorporated.map((keyword) => (
              <span key={keyword} className="chip is-exact">
                {keyword}
              </span>
            ))}
          </div>
        </>
      )}
      {match?.newly_evidenced.length > 0 && (
        <p className="report-meta">Requirements with more evidence now: {match.newly_evidenced.join(', ')}.</p>
      )}
      {match?.still_missing.length > 0 && (
        <p className="report-meta">
          Still not evidenced (not added, because your resume doesn't show them): {match.still_missing.join(', ')}.
        </p>
      )}
      <p className="quality-disclaimer">{scores.disclaimer}</p>
      {match && <p className="quality-disclaimer">{match.method}</p>}
    </section>
  )
}
