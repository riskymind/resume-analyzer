# Job Matching Methodology

_Version **job-match/1** · implemented in `backend/app/services/matching/` · configuration in
`matching/config.py` · every match stores the version that produced it, and the full configuration
snapshot is in the `matching_configs` table._

The job match percentage estimates **how well a resume evidences the requirements a job description
states**. Application code calculates it from verified data. The AI model never produces, adjusts or
reviews the number. The match is independent of the resume quality score
([scoring-methodology.md](scoring-methodology.md)): neither reads nor changes the other.

> The match cannot see skills the resume does not mention, and it does not predict any employer's
> hiring decision. A missing requirement means **missing resume evidence**, not proof that the
> candidate lacks the skill.

## 1. Pipeline

```
job description (text | PDF | DOCX | Markdown)
  └─ AI extraction (proposes requirements)           app/services/job_extraction.py
      └─ verification against the original text      (drops anything not in the posting)
          └─ required/preferred from the text's own wording
              └─ lexicon scan adds well-known skills the model missed
structured resume (verified in Milestone 3)
  └─ semantic signals (embeddings, cached)            app/services/matching/semantic.py
      └─ deterministic engine (pure function)         app/services/matching/engine.py
          └─ match report + stored inputs             job_matches.report / job_matches.inputs
```

## 2. Job description extraction and validation

Each requirement has: `name`, `category` (`technical_skill`, `soft_skill`, `experience`, `education`,
`certification`, `responsibility`), `classification` (`required` | `preferred`),
`classification_source` (`text` | `ai` | `default`), `importance` (`high` | `medium` | `low`), verbatim
`evidence`, `status` (`verified` | `detected`), optional `min_years`, and optional
`alternative_group`.

Verification rules (all deterministic):

| Rule | Effect |
|---|---|
| Evidence must appear in the job description (normalised comparison). | Otherwise the sentence that names the requirement is used; if none exists, the item is discarded. |
| Technical skills and certifications must be **named** in the text (directly or by a known alias). | Stops the model adding "typical" skills the employer never wrote. |
| `min_years` comes from the evidence text ("5+ years", "3-5 years", "five years"). | A model-supplied number that the evidence does not state is dropped. |
| Required vs preferred: preferred cues ("nice to have", "preferred", "a plus", "bonus", "desirable", "optional"…) or required cues ("required", "must", "requirements", "essential", "qualifications"…) in the sentence, or a heading above it, decide. When a sentence has both ("Python required, Scala is a plus"), the clause naming the item decides. | `classification_source = "text"`, and the model's label is ignored. Re-classifications are counted and reported. |
| Text gives no cue. | The model's label is kept (`ai`), or `required` if it gave none (`default`). |
| Lexicon scan finds a well-known skill the model missed. | Added as `status = "detected"`, importance `low`, and **preferred unless the text says required**, so "our stack includes Docker" never becomes mandatory. |
| "A or B" / "A/B" between two skills sharing the same evidence. | Grouped as alternatives; only directly adjacent pairs are grouped, so in "Python, FastAPI or Django" Python stays mandatory. |
| Duplicates (aliases such as Postgres/PostgreSQL). | Merged. |
| Keywords. | The model's keywords must appear in the text; lexicon skills found in the text are added (up to 30 in total). |

## 3. Matching rules per requirement

**Credits** (share of the requirement's weight awarded):

| Outcome | Status | Credit |
|---|---|---|
| Skill named in the resume (skills list, project technologies, bullets, summary or text), alias-aware | `matched` (`exact`) | 1.00 |
| Soft skill demonstrated by a verbatim resume sentence (inferred in Milestone 3) | `matched` (`evidenced`) | 1.00 |
| Different skill in the same family (Django for FastAPI, AWS for GCP) | `related` (`related_lexicon`) | **0.35** |
| Embedding similarity ≥ **0.80** between requirement and a resume skill (different skill) | `related` (`related_semantic`) | **0.35** |
| Years: candidate ≥ required | `matched` | 1.00 |
| Years: 0 < candidate < required | `partial` | candidate ÷ required |
| Years: skill evidenced, but no dated role shows it | `partial` | 0.35 |
| Experience/responsibility wording: ≥ 60% of the requirement's content words in one resume entry | `matched` (`text_overlap`) | 1.00 |
| Experience/responsibility: embedding similarity ≥ **0.82** with a resume bullet | `partial` (`semantic_text`) | 0.60 |
| Experience/responsibility: 34–59% word overlap | `partial` | 0.50 |
| Education: level met and field matches (or no field specified) | `matched` | 1.00 |
| Education: level met, different field (or level not determinable) | `partial` | 0.50 |
| Education: lower level than required | `partial` | 0.25 |
| Certification listed (≥ 80% token overlap) or named in the text | `matched` | 1.00 |
| Different certification from the same vendor | `related` | 0.35 |
| No evidence | `missing` | 0 |

Related matches are **never** equivalent. They appear in their own list, earn partial credit, and
their explanation says the requirement is not considered met. Semantic similarity never produces an
exact match.

**Ambiguous skills** ("Go", "R", "C", "Swift", "REST") are matched only against explicit skill
lists, never by searching free text ("ready to go" does not mean Go). Unambiguous aliases such as
"golang" are still searched.

**Years of experience**:
- Role intervals come from parsed start/end dates. "Present" is the match's `as_of` date, which is
  stored with the match.
- Year-only dates count from January, so "2018–2021" is 3 years, a conservative reading.
- Overlapping roles are merged, never double-counted.
- When the requirement names a skill ("5+ years Python"), only roles whose title or bullets mention
  that skill count.
- Years the resume itself states ("6 years of experience building Python APIs") count when the
  sentence mentions the skill.
- The candidate's figure is the larger of the dated and stated values.

**Alternatives**: a group is scored once, by its best-evidenced member. The others are shown with
`counted = false` and are excluded from the score, the missing-skills list, the caps and the keyword
list.

## 4. Score formula

Requirements are assigned to components:

| Component | Members | Weight |
|---|---|---|
| Required skills | required technical + soft skills | **35** |
| Required experience | required experience requirements | **20** |
| Responsibility alignment | responsibilities | **10** |
| Required education | required education | **8** |
| Required certifications | required certifications | **5** |
| Preferred qualifications | every preferred requirement (any category except responsibility) | **12** |
| Job keywords | job keywords | **10** |

```
requirement weight     w = importance weight (high 1.5, medium 1.0, low 0.5)
component score        S_c = 100 × Σ(credit × w) / Σ w          (keywords: 100 × present / total)
effective weight       E_c = W_c × 100 / Σ W_k over components that have members
match (before caps)    M = Σ E_c × S_c / 100, rounded half-up to an integer
```

**Normalisation**: components with no requirements for this job are dropped, and the remaining
weights are re-scaled to 100. A job with no certification requirement is not penalised for that.
Similarities are rounded to 4 decimal places before comparison, so floating-point noise cannot
change a result. Configuration validation enforces that the required components together outweigh
the preferred component.

**Caps** (a missing mandatory requirement keeps the match below "Strong"):
- If any counted mandatory requirement (non-responsibility) is `missing`, the match is capped at **79**.
- If more than half are missing, the match is capped at **59**.

The reason is shown in `score_cap`. Missing preferred qualifications never trigger a cap.

**Labels** (unchanged from the original app): ≥ 80 Strong Match · ≥ 60 Good Match · ≥ 40 Fair Match · < 40 Weak Match.

**Confidence** (not part of the score):
- `low` when fewer than three requirements could be verified.
- `medium` when semantic matching was unavailable or disabled, or when years were required but no
  role has parseable dates.
- `high` otherwise.

`evidence_coverage` is the percentage of counted requirements with any supporting resume evidence.

## 5. Semantic matching (decision D7)

- **What is embedded**: requirement skill names; resume skill names and project technologies;
  requirement sentences for experience and responsibility requirements; individual resume bullets,
  the summary and project descriptions. Whole resumes are never embedded. Each text is truncated to
  400 characters, and each match is capped at `EMBEDDING_MAX_TEXTS` (150).
- **Model**: `GEMINI_EMBEDDING_MODEL` (default `gemini-embedding-001`), `EMBEDDING_DIMENSIONS` (768),
  task type `SEMANTIC_SIMILARITY`. Inputs are sent in batches of up to 100 texts.
- **Cache** (`embedding_cache`):
  - Key: `sha256(model | dimensions | scope | normalised text)`. Normalisation is NFKC, collapsed
    whitespace and lowercase.
  - Changing the model or the dimensions never reuses old vectors.
  - Short terms (≤ 60 characters, such as "kubernetes") are shared across users (`scope = *`).
  - Longer texts are personal and are cached per user; they are deleted with the account.
  - Concurrent inserts use `ON CONFLICT DO NOTHING`.
- **Quota**: a match counts against the per-user AI limit only when uncached embeddings must be
  fetched.
- **Fallback**: any provider error (timeout, quota, malformed vectors) gives
  `semantic.status = "unavailable"` with the reason, and matching continues with exact, alias and
  lexicon-family rules only. The report states this and lowers the confidence; fallback results are
  never labelled semantic. `SEMANTIC_MATCHING_ENABLED=false` gives `status = "disabled"`.
- **Determinism**: similarities are computed before scoring and stored in `job_matches.inputs`
  together with `as_of`. `reproduce_report()` recomputes a stored match exactly, with no AI call.

## 6. Worked examples

**Example 1: sample backend job** (the regression fixture). The resume (Jane Doe) lists Python,
FastAPI, PostgreSQL, Docker, Kubernetes and AWS, states "6 years of experience building Python APIs",
and has a BSc in Computer Science.

| Requirement | Class | Result | Credit |
|---|---|---|---|
| 5+ years Python | required (high) | matched: 6 years stated | 1.0 |
| Python (high), PostgreSQL, Docker, Kubernetes | required | matched (exact) | 1.0 |
| FastAPI **or** Django | required, alternatives | FastAPI matched; Django not counted | 1.0 |
| Terraform (low) | preferred, re-classified from the "Nice to have:" text | missing | 0 |
| GCP (low) | preferred | related: AWS is in the same cloud family | 0.35 |
| Bachelor's in Computer Science or related field | required | matched | 1.0 |
| Keywords: Backend, Python, Kubernetes, Terraform, FastAPI, PostgreSQL, Docker, GCP | – | 6 of 8 present | 75% |

Applicable weights: 35 + 20 + 8 + 12 + 10 = 85, re-scaled to 41.18 / 23.53 / 9.41 / 14.12 / 11.76.
Preferred = (0 × 0.5 + 0.35 × 0.5) / 1.0 = 17.5%.
**M = 41.18 + 23.53 + 9.41 + 14.12 × 0.175 + 11.76 × 0.75 = 85.41 → 85 (Strong Match)**, no cap.

**Example 2: a missing mandatory skill.** Required skills only: Python, Django, PostgreSQL, AWS
(medium, matched) and Rust (low, missing). S = (4 × 1.0) / (4 + 0.5) = 88.9 → M = 89, **capped at 79**
(Good Match): "1 mandatory requirement(s) have no evidence in the resume."

**Example 3: re-normalisation.** One required skill (matched, 100), one preferred skill (missing, 0),
two keywords of which one is present (50). Weights 35 / 12 / 10 → 61.40 / 21.05 / 17.54.
M = 61.40 + 0 + 8.77 = 70.18 → **70**.

## 7. Limitations

- Similarity thresholds (0.80 skill, 0.82 text) and the lexicon families are reasoned defaults. They
  have not been calibrated against a labelled dataset or the live Gemini embedding model, so expect
  to tune them; bump `version` when you do.
- The lexicon covers 113 common technologies and practices. Unknown skills are still matched exactly by name,
  but they have no family, so related matches for them rely on embeddings alone.
- Text matching for experience and responsibility requirements is word-overlap based, and can miss
  paraphrases when embeddings are unavailable.
- Degree levels and fields are recognised from common English wording ("BSc", "Master's",
  "Computer Science"). "Or equivalent experience" clauses are reported but cannot be verified.
- Seniority alignment compares title keywords only, and is informational (not scored).
- Grouping of alternatives is deliberately conservative: in "React, Vue or Angular" only Vue and
  Angular are grouped.
- A requirement extracted under the wrong category by the model is still scored under that category.
  Its evidence is genuine, but its treatment may be imperfect; the requirement list is shown to the
  user for review.
