# Resume Quality Scoring Methodology

_Scoring version: `resume-quality/1` (stored with every saved report).
Code: `backend/app/services/scoring/` · Config: `backend/app/services/scoring/config.py`._

## 1. Principles

1. **Code computes every number.** The AI model only *proposes* a structured reading of the resume
   (roles, bullets, skills…). Application code checks each proposed value against the resume text
   and discards anything it cannot find (see §6) before scoring. The model never outputs a score.
2. **Job-independent.** Nothing about a target job reaches the scorer: `score_resume(data, config)`
   takes only the document, its sections and the verified structure. A resume does not score worse
   because it is being compared with an unrelated job. Job matching is a separate score
   (Milestone 4).
3. **Explainable.** Every lost point belongs to a named deduction with a message, a concrete fix
   and, where useful, the quoted evidence.
4. **Deterministic.** The same document and configuration always produce the same report (tested).
5. **No invented content.** Recommendations never ask users to make up figures. The quantification
   advice explicitly says: _"Do not estimate numbers you cannot support."_

## 2. Overall score

```
dimension score   = max(0, 100 − Σ deduction points)          (0–100, per dimension)
overall (exact)   = Σ (weight × dimension score) / 100         (weights sum to 100)
overall score     = round-half-up(overall exact)
if word count < 150: overall score = min(overall score, 70)    (with an explanation in score_cap)
```

| Dimension | Weight | What it measures |
|---|---|---|
| Contact information | 10 | Name, email, phone, a professional link, location |
| Structure and length | 10 | Core sections present; overall length |
| Professional summary | 10 | Present, right length, specific, not cliché or first person |
| Experience descriptions | 20 | Complete roles; enough, well-formed bullets; action verbs; order |
| Achievements and impact | 15 | Share of bullets with measurable results; outcome-focused bullets |
| Skills | 10 | Number of technical skills and whether experience backs them up |
| Education | 5 | Entries with qualification, institution and dates |
| Formatting consistency | 10 | One date style, bullets not paragraphs, no shouting, no icon clutter |
| Readability | 10 | Reading ease, sentence length, passive voice, repeated verbs |

Labels: **Excellent** ≥ 90 · **Strong** ≥ 75 · **Fair** ≥ 60 · **Needs work** < 60.

**Why the cap?** Length is only 10% of the weighting, so a polished 70-word resume could otherwise
rate "Strong" or better. Under 150 words a resume cannot show enough depth, so the overall score is
capped at 70. The cap is reported in `score_cap`, and the uncapped dimension scores remain visible.

## 3. Deductions by dimension

Points are subtracted from that dimension's 0–100 score. "each, max N" applies per affected item,
capped. The impact on the overall score is `points × weight / 100`. That impact figure is what the
UI shows as "up to +X points".

### Contact information (10%)
| Code | Points | Trigger |
|---|---|---|
| `contact.email_missing` | 40 | No email found anywhere |
| `contact.name_missing` | 20 | No name from the model (verified) or from the first header line |
| `contact.phone_missing` | 20 | No 9–15 digit phone number (year ranges excluded) |
| `contact.links_missing` | 10 | No LinkedIn, GitHub or website |
| `contact.location_missing` | 10 | No verified location |

Email, phone and links are found by deterministic parsing, not by the model.

### Structure and length (10%)
| Code | Points | Trigger |
|---|---|---|
| `structure.experience_missing` | 35 (20 if projects are present) | No experience section and no roles extracted |
| `structure.education_missing` | 20 | No education section or entries |
| `structure.skills_missing` | 15 | No skills section and fewer than 3 technical skills |
| `structure.too_short` / `short` | 40 / 10 | < 150 / < 250 words |
| `structure.too_long` / `long` | 25 / 15 | > 1800 / > 1200 words |

### Professional summary (10%)
| Code | Points | Trigger |
|---|---|---|
| `summary.missing` | 60 | No summary/profile/objective |
| `summary.too_short` / `too_long` | 25 / 20 | < 20 / > 100 words |
| `summary.first_person` | 10 | "I", "me", "my"… used 2+ times |
| `summary.buzzwords` | 15 | 2+ clichés (hard-working, team player, results-driven…) |
| `summary.generic` | 10 | No digits and no listed skill mentioned |

### Experience descriptions (20%)
| Code | Points | Trigger |
|---|---|---|
| `experience.none` | 100 (50 if projects are present) | No roles extracted |
| `experience.title_missing` / `employer_missing` | 10 each, max 30 | Role without a verified title / employer |
| `experience.dates_missing` | 8 each, max 24 | Role without a verified start date |
| `experience.few_bullets` / `many_bullets` | 8 each, max 24 / 5 each, max 15 | < 2 / > 8 bullets in a role |
| `experience.thin` | 15 | < 4 bullets across all roles |
| `experience.action_verbs_poor` / `action_verbs` | 15 / 8 | < 50% / < 70% of bullets open with an action verb |
| `experience.weak_phrases` | 4 each, max 16 | "responsible for", "worked on", "duties included"… |
| `experience.long_bullets` / `thin_bullets` | 10 / 8 | Average bullet > 35 / < 5 words |
| `experience.order` | 5 | Start dates not in reverse-chronological order |
| `experience.date_range` | 5 each, max 10 | End date before start date |

### Achievements and impact (15%)
Quantified bullets contain a currency amount, percentage, multiplier (3x), scaled number (2M, 10k),
grouped number (1,200,000) or a count followed by a noun ("5 engineers"). Bare years don't count.

| Share of bullets quantified | ≥ 40% | ≥ 25% | ≥ 10% | > 0% | 0% |
|---|---|---|---|---|---|
| `achievements.quantified` points | 0 | 15 | 35 | 50 | 70 |

Plus `achievements.no_bullets` (70) when there are no bullets, and `achievements.none` (10) when no
bullet is an outcome.

### Skills (10%)
| Code | Points | Trigger |
|---|---|---|
| `skills.none` | 60 | No verified technical skills |
| `skills.few` / `too_many` | 25 / 15 | < 5 / > 40 skills |
| `skills.unevidenced` | 15 | With 5+ skills, under 30% appear in experience, projects or summary |

### Education (5%)
`education.none` 60 (40 if certifications are listed), plus qualification or institution missing at
15 each (max 30), and dates missing at 10 each (max 20).

### Formatting consistency (10%)
`formatting.date_styles` 15 (more than one of `Mon YYYY`, `Month YYYY`, `MM/YYYY`, `YYYY`) ·
`formatting.paragraphs` 10 each (max 20; > 50-word non-bullet lines in Experience) ·
`formatting.all_caps` 5 each (max 10) · `formatting.symbols` 10 (> 10 icons/emoji/private-use glyphs).

### Readability (10%)
Flesch Reading Ease over the summary and bullets: `readability.very_hard` 25 (< 10),
`readability.hard` 12 (< 25). Average sentence length: 15 (> 30 words), 8 (> 25).
`readability.passive` 10 (> 30% passive bullets). `readability.repeated_verbs` 5 per verb (max 15)
for an opening verb used 4+ times.

## 4. ATS compatibility score (separate)

`ats_score = 100 − Σ points of failed checks`. It is reported next to the overall score and is not
part of it.

| Check | Points | Fails when |
|---|---|---|
| `ats.text_layer` | 30 | (Always passes: unreadable files are rejected at upload) |
| `ats.image_pages` | 20 | Some PDF pages have no selectable text |
| `ats.standard_headings` | 10 per missing, max 30 | No recognisable Experience / Education / Skills heading |
| `ats.contact_in_body` | 15 | DOCX email appears only in the page header |
| `ats.tables` | 15 | DOCX uses tables |
| `ats.file_format` | 10 | Markdown (most ATS accept only PDF/DOCX) |
| `ats.symbols` | 10 | More than 5 icons or symbols |
| `ats.dates` | 10 | A role has no parseable start date |
| `ats.length` | 5 | More than 3 pages or 1800 words |

> The ATS compatibility score estimates how reliably automated applicant tracking systems can read
> the document. It does not predict or guarantee that an application will pass any employer's
> screening. This disclaimer is included in every report.

## 5. Worked examples (actual engine output)

**A. Strong, full resume** (`FULL_RESUME` in `backend/tests/unit/test_scoring.py`: 3 roles,
10 bullets, all quantified, 209 words, PDF)

| Dimension | Weight | Score | Contribution | Deductions |
|---|---|---|---|---|
| Contact | 10 | 100 | 10.0 | |
| Structure | 10 | 90 | 9.0 | −10 `structure.short` (209 words) |
| Summary | 10 | 100 | 10.0 | |
| Experience | 20 | 100 | 20.0 | |
| Achievements | 15 | 100 | 15.0 | |
| Skills | 10 | 100 | 10.0 | |
| Education | 5 | 100 | 5.0 | |
| Formatting | 10 | 100 | 10.0 | |
| Readability | 10 | 100 | 10.0 | |
| **Overall** | | | **99.0 → 99 (Excellent)** | ATS 100 |

**B. Thin resume** (`SAMPLE_RESUME_MD`: 2 roles, 3 bullets, 72 words, Markdown)

| Dimension | Score | Deductions |
|---|---|---|
| Contact | 90 | −10 location missing |
| Structure | 60 | −40 too short (72 words) |
| Summary | 75 | −25 too short (9 words) |
| Experience | 77 | −8 one role with < 2 bullets; −15 only 3 bullets in total |
| Achievements, Skills, Education, Formatting, Readability | 100 | |

Weighted total 9 + 6 + 7.5 + 15.4 + 15 + 10 + 5 + 10 + 10 = **87.9**, which rounds to 88. The resume
has only 72 words, so the overall score is **capped at 70 (Fair)**. ATS score 90 (−10, Markdown).
Top fix: "Describe your experience in more detail; most resumes need 300–800 words." (+4.0 points)

## 6. Extraction verification (what the scorer can trust)

| Field | `explicit` when | `inferred` allowed? |
|---|---|---|
| Employer, job title, dates, institution, qualification, certification, technical skill, bullet text, summary | The value appears in the resume (case-, whitespace- and dash-insensitive, word-boundary match) | **No.** Otherwise discarded. |
| Soft skill | The name appears in the resume | Yes, if the quoted evidence sentence appears verbatim |
| Location, language proficiency | The value appears | Yes, with verbatim evidence |
| Name | The model's name appears | Falls back to the first header line (marked `inferred`) |
| Email, phone, links | Deterministic regex on the document | n/a |

Discarded items are counted in `extraction.removed_items` and reported to the user. The status is
assigned by code, never taken from the model's own claim. Verification proves that text *exists in
the resume*, not that it is *true*. A false claim the user wrote themselves is treated as their
content.

## 7. Changing the methodology

- Weights and thresholds live in `ScoringConfig`. Weights must cover every dimension and sum to 100,
  or construction fails.
- Word lists (action verbs, weak phrases, buzzwords) live in `scoring/lexicon.py`.
- **Bump `ScoringConfig.version` whenever a change can alter scores.** Saved reports keep the
  version that produced them, so old and new scores are never silently mixed.
- Add or adjust a test in `tests/unit/test_scoring.py` for every rule change.
