# AI Resume Rewriting

_Milestones 5–6 · prompt version **resume-rewrite/1** · code in `backend/app/services/rewriting/`,
`backend/app/documents/`, `backend/app/api/routes/rewrites.py` · audience: developers and reviewers of this
project._

The rewriter improves how an existing resume presents the candidate's **real** experience. It is an
editor, not an author. The AI proposes wording, and application code decides what may reach the
document. The source resume is never modified; every rewrite is saved separately as a history of
immutable versions.

## 1. Architecture

```
source resume (verified StructuredResume, Milestone 3)
  └─ build_document()  → ResumeDocument with stable ids (exp-1, exp-1-b2, proj-1 …)   document.py
optional job (verified StructuredJob, Milestone 4)
  └─ deterministic match of the original (semantic off) → evidenced / related / missing requirements
          │
          ▼
  prompt (rewrite_prompts.py): content by id, no contact details, no organisation names; job requirements,
  required first; "not_evidenced" requirements named as gaps
          │  AIProvider.generate_json()  (existing Gemini adapter, timeouts and retries)
          ▼
  AIRewriteOutput (Pydantic, lenient, length-capped)  ── malformed → 502, nothing saved
          │
          ▼
  generator.py: one Suggestion per unit, unknown ids / out-of-scope items discarded
          │
          ▼
  verification.py: every suggestion checked against ITS OWN source evidence
          ├─ blocking → auto-rejected, cannot be accepted
          ├─ warning  → waits for the user's decision
          └─ clean    → applied (still reversible)
          │
          ▼
  service.py: compose(original + applied suggestions + manual edits) → verify_document() → scores.compare()
          │                                                     (existing deterministic engines)
          ▼
  resume_rewrite_versions (immutable)  ──►  preview (HTML) / PDF (WeasyPrint) / DOCX (python-docx)
```

| Module | Responsibility |
|---|---|
| `schemas/rewrite.py` | Document, request, suggestion, verification, score and untrusted AI-output schemas |
| `ai/rewrite_prompts.py` | System instructions and fenced user content; kept separate from logic |
| `services/rewriting/document.py` | Original document from the verified extraction; canonical text rendering; conversion back to `StructuredResume` for scoring |
| `services/rewriting/generator.py` | Prompt payloads, provider call, output validation, suggestion building, gaps, metric prompts |
| `services/rewriting/verification.py` | Deterministic factual checks for suggestions and for whole saved documents |
| `services/rewriting/scores.py` | Before/after quality and match scores via the existing engines |
| `services/rewriting/service.py` | Create, regenerate, decisions, edits, restore; composition; versioning |
| `repositories/rewrites.py` | User-scoped persistence, pruning, cleanup on resume/job/account deletion |
| `documents/` | Template registry, Jinja HTML template, WeasyPrint PDF, python-docx DOCX |

## 2. Factual verification

**By construction.** The model never outputs employers, job titles, dates, locations, degrees,
institutions or certification names. It refers to items by id, and application code copies those facts
from the original. Education and certification items can only be reordered. Skills can only be
reordered: names the model adds are removed and recorded; names it omits are kept.

**By checking.** Every rewritten text unit is compared with its **own evidence**:

| Unit | Evidence |
|---|---|
| Experience bullet | The original bullet(s) it cites in `source_ids` (same role only), plus the role's title and employer |
| Project description | The original project's name, description and technologies |
| Summary | The whole original resume |

| Check | Severity | Example caught |
|---|---|---|
| Every number/percentage/amount/year exists in the evidence with the same unit, scale and currency (spelled numbers included) | blocking | "45%" for "35%", "99.9% uptime", "2B" for "2M", "$2M" for "2M requests", a figure moved from another bullet |
| Years-of-experience claims | blocking | "8 years of experience" when the resume says 6 |
| Implied quantities ("dozens", "millions", "a decade") | blocking | "handling millions of requests" |
| Skills, tools, job-required skills and certifications must be mentioned in the resume (alias-aware; ambiguous names like Go/R/REST detected by their capitalised form) | blocking | Terraform, GCP; Django presented for FastAPI experience |
| Degrees and certifications ("MSc", "AWS Certified …") | blocking | an invented MSc |
| The target employer's name, the target job title | blocking | "Senior Backend Engineer with…" when that title was never held |
| Organisations ("at Google", "… Inc", "… University") must be in the bullet's own evidence (summary: the verified structure). Mentions elsewhere in the raw text, including injected text, do not count | blocking | "at Google" |
| Leadership/ownership words when the evidence has none | blocking | "Managed the team that built…" |
| Bullets citing no source | blocking | a brand-new bullet |
| Unverified capitalised names, scope words (company-wide, worldwide), superlatives, substantially new content (> 50 % new content words, ≥ 4 words) | warning | "for Contoso clients", "world-class" |
| A resume skill moved into a bullet whose source does not mention it | warning | "on PostgreSQL" added to the FastAPI bullet |

**Manual edits** go through the same checks, plus a comparison of locked fields (title, employer,
dates, institution, qualification, certification) against the original by id. They are tagged
`origin: "user"` and kept: the user is the authority on their own history, but the UI shows them
as unsupported and never as verified. **Export of unverified content needs explicit confirmation**
(Milestone 6): when the version being exported has any blocking or warning issue, the export panel lists
every unverified claim, keeps the download buttons disabled until the user ticks "I have checked these
claims and confirm they are accurate", and sends `acknowledge_unverified: true`. The server enforces the
same rule (`409 acknowledgement_required` without it), records the confirmation and the version's
verification status in the export metadata, and never removes the user's text. A confirmation applies to
one version only: it resets when the version on screen changes.

**Relevant coursework** (Milestone 6) is an optional list per education entry, entered by the user. A
course must appear in the original resume text; otherwise it is a blocking, user-authored
`unsupported_coursework` issue. The AI extraction does not capture coursework, and the model never sees
or writes it.

**Metrics.** If a bullet would benefit from a figure the resume does not give, the model may add a
*question* (`metric_prompt`); prompts containing digits are dropped. Numbers are never generated.

**Gaps.** Requirements the original resume does not evidence (and "related" matches such as GCP for
AWS) are listed as gaps with an explanation. They are never written into the resume.

## 3. Suggestions, decisions and composition

A suggestion is **applied** when `decision = accepted`, or `decision = pending` and verification is
`verified`. Warnings wait for review; blocked suggestions are `rejected` with `auto_rejected = true`,
and accepting one returns `409 suggestion_blocked`.

Content is composed **per unit** (`summary`, `experience:<id>`, `skills`, `project:<id>`, `education`,
`certifications`). For a role, original bullets keep their order; each is replaced by the applied
suggestion(s) that cite it, and merged bullets replace all their sources. Accepting, rejecting or
regenerating rebuilds only the affected unit, so manual edits elsewhere survive (the UI warns that
edits inside that unit are reset).

## 4. Prompt design

- Instructions are in the provider's system channel only. The resume and job data are JSON inside
  `<resume>` / `<job_description>` fences that the content cannot close (`fence()` neutralises
  lookalike tags). The shared `UNTRUSTED_DATA_RULES` tell the model never to follow instructions found
  in documents.
- **Data minimisation:** name, email, phone, links, location, employer names, institution names and
  grades are not sent. Job requirements are sent without the employer's name.
- The job payload lists required requirements first (then importance), which requirements the resume
  evidences, which are only *related* ("not equivalent"), and which are `not_evidenced` (gaps).
- Modes: `professional`, `ats`, `job_targeted` (needs a job), `executive`. Scope `keywords` adds a
  "smallest edits" instruction.
- Output is JSON validated by Pydantic. `alignment_notes` (the "how this targets the job"
  explanation) are length-capped, notes making blocking claims are dropped, and the UI labels them as
  AI commentary.
- Even an obedient-to-injection model cannot get a fabrication into the document: verification is
  independent of the prompt (see `test_prompt_injection_in_resume`).

## 5. Scores (before / after)

Both scores are recalculated **by the existing deterministic engines from the saved content** on every
version. Gemini never produces a score.

- **Quality / ATS:** the original and the rewrite are rendered through the same canonical layout
  (`render_text`) and scored by `score_resume`. The uploaded file's own score is shown alongside for
  reference; it can differ because file formatting is also scored.
- **Job match:** `match_resume_to_job` on both versions with semantic similarity **disabled for both**.
  Embeddings would need AI calls on every edit, and both sides must be measured identically. A saved
  match report (which may use embeddings) is shown for reference.
- The UI and API carry a disclaimer: a score improvement is not a guarantee of an interview.

## 6. Database (migrations `0005`, `0006`)

| Table | Key columns | Notes |
|---|---|---|
| `resume_rewrites` | `user_id` → users (CASCADE), `resume_id` → resumes (CASCADE), `job_description_id` → job_descriptions (**SET NULL**), `name`, `mode`, `template`, `current_version`, `original` (JSON snapshot) | Index `(user_id, updated_at)` |
| `resume_rewrite_versions` | `rewrite_id` (CASCADE), `user_id`, `number`, `source` (generate / regenerate / decisions / edit / restore), `content`, `suggestions`, `verification`, `scores`, `generation` (JSON), denormalised `verification_status`, `quality_after`, `match_after` | `UNIQUE(rewrite_id, number)` gives optimistic concurrency; a conflict returns 409 |
| `resume_rewrite_exports` | `rewrite_id` (CASCADE), `user_id`, `version_number`, `format`, `template`, `size_bytes` | Metadata only; files are streamed, never stored |

- Every query filters on `user_id` in SQL; another user's rewrite returns the same 404 as a missing one.
- Versions are pruned to `REWRITE_MAX_VERSIONS` (default 30); version 1 is always kept.
- Deleting a resume deletes its rewrites. Account deletion explicitly deletes all three tables (FK cascades
  are a second line of defence).
- **Deleting a job** (Milestone 6 rules) keeps the rewrite and **all** its versions, and:
  - unlinks it (`job_description_id = NULL`) and sets `job_detached_at`;
  - removes from every version the match comparison (scores, newly evidenced and still-missing
    requirements), keywords incorporated, gaps, the model's alignment notes, and each suggestion's
    keywords, requirement ids and rationale (the model's explanation may describe the job);
  - rewrites the messages of job-specific verification issues (`target_title`, `target_employer`,
    `unsupported_keyword`) without the job's wording, **keeping their severity**, so a claim never
    becomes "verified" because the job was deleted;
  - renames a rewrite whose name is still the default "<resume> – <job title>" to "<resume> – target job
    deleted"; names the user chose are kept;
  - shows "target job deleted" in the saved list and a notice in the workspace. No job-match score is
    shown, and later regenerations fall back from job-specific to professional mode.
- Migration `0006` adds `resume_rewrites.job_detached_at` and, on `resume_rewrite_exports`,
  `verification_status` and `acknowledged_unverified`. It is additive; downgrade to `0005` drops only
  those columns.
- Up/down/up is tested on SQLite and PostgreSQL 16 for `0005` and `0006`.

## 7. API (`/api/v1`, session cookie; state-changing calls need `X-CSRF-Token` + trusted Origin)

| Method | Path | Notes |
|---|---|---|
| GET | `/resumes/{id}/document` | Original resume as an editable document with ids (for choosing bullets) |
| GET | `/rewrites/templates` | `modern`, `minimal`, `corporate`, `technical`, `graduate` |
| POST | `/rewrites` | `{resume_id, job_id?, scope, mode?, bullet_ids?, name?}` → 201 detail. Counts against the AI quota only after validation |
| GET | `/rewrites[?resume_id=]` | Summaries with before/after scores and verification status |
| GET | `/rewrites/{id}[?version=n]` | Detail: original, content, suggestions, verification, scores, generation info, version list |
| PATCH | `/rewrites/{id}` | `{base_version, name?, template?}` plus at most one of `decisions`, `content`, `restore_version`. Stale `base_version` → 409 |
| POST | `/rewrites/{id}/regenerate` | `{base_version, scope, bullet_ids?, mode?}`; bullet ids may be original or rewritten ids. AI quota |
| DELETE | `/rewrites/{id}` | Deletes versions and export metadata |
| GET | `/rewrites/{id}/preview[?template=&version=]` | `{template, version, html}`, the HTML the PDF is made from |
| POST | `/rewrites/{id}/export` | `{format: pdf\|docx, template?, version?, acknowledge_unverified?}` → attachment. Unverified content without the acknowledgement → `409 acknowledgement_required`. Limited by `EXPORT_MAX_PER_MINUTE` (default 10) |

Errors use the standard envelope (`{"detail", "error": {"code", "message", "request_id"}}`), e.g.
`nothing_to_rewrite`, `unknown_bullet`, `job_required`, `suggestion_blocked`, `conflict`,
`ai_upstream_error` (502), `ai_not_configured` (503), `export_unavailable` (503), `acknowledgement_required`
(409), `empty_resume`,
`rate_limited` (429). Logs record ids, counts and statuses, never resume content.

## 8. Exports

- One template definition (`documents/templates.py`) drives both outputs: fonts, accent colour,
  heading style, header alignment and section order.
  - **Modern professional:** Calibri/Carlito, teal accent, ruled uppercase headings.
  - **Minimalist:** Arial/Liberation Sans, black only, no rules.
  - **Traditional corporate:** Times New Roman/Liberation Serif, centred header, education before skills.
  - **Technical** (Milestone 6): Arial/Liberation Sans, compact, skills first, then experience and
    projects; each project shows its "Tech stack:" line before the description.
  - **Graduate** (Milestone 6): Cambria/Caladea, centred header, education (with relevant coursework)
    first, then projects, then experience (including internships).
  - All five are single column with standard headings and no tables or graphics. Continuation pages
    carry a footer "Name — page n of N" (CSS `@page` in the PDF, Word `PAGE`/`NUMPAGES` fields in the
    DOCX, with a different first page); contact details stay in the body. QA results and the manual Word
    checklist: [export-qa.md](export-qa.md).
- **PDF:** the preview HTML (Jinja, autoescaped) rendered by WeasyPrint. Single column, A4,
  `break-inside: avoid` on bullets, headings kept with their content, clickable `mailto:` and web links.
  WeasyPrint gets a URL fetcher that refuses every request, so document content cannot cause SSRF or
  local file reads. Stray bullet glyphs and control characters are removed.
- **DOCX:** python-docx. Real paragraphs (no tables or text boxes), Word's "List Bullet" style, contact
  details in the body (not the page header), clickable hyperlinks, right-aligned dates via tab stops,
  keep-with-next on headings.
- Exports are generated on demand from the requested (default: latest) version and streamed with
  `Content-Disposition: attachment; filename="<name>-resume.pdf"`, `Cache-Control: no-store` and
  `X-Content-Type-Options: nosniff`. Filenames are ASCII slugs. Only metadata is stored.
- **System requirement:** WeasyPrint needs Pango (`libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b`) and
  fonts (`fonts-liberation fonts-crosextra-carlito fonts-crosextra-caladea fonts-dejavu-core`; Caladea is
  for the Graduate template); add `libharfbuzz-subset0`, which WeasyPrint 70 warns will be required by future versions. Without them, PDF export returns a
  clear `503 export_unavailable` and DOCX still works. On macOS: `brew install pango`. The production
  Dockerfile (Milestone 8) must install these packages.

## 9. Known limitations

- **Meaning changes without new facts are only partly detectable.** The checks catch new numbers,
  names, skills, qualifications, leadership and scope words, and large amounts of new content. A
  subtle verb change ("maintained" → "improved") is not detected. Users review every change, and
  the before/after diff highlights each word changed.
- Name detection is heuristic (capitalisation). It can warn on harmless words such as a new acronym,
  and it relies on capitalisation, so a lower-case invented name is caught only by the novelty check.
- Only sections in the verified extraction (contact, summary, experience, education, skills,
  certifications, projects, languages) are rewritten and exported. Other sections of the uploaded file
  (awards, volunteering…) are not carried over.
- Bullets keep their original order within a role; reordering by relevance is not applied.
- Manual edits inside a role are reset when a suggestion in that role is accepted or rejected
  afterwards (the UI warns about this).
- Generation is synchronous (typically 10–60 s; bounded overall by `AI_TOTAL_TIMEOUT_SECONDS`, retries included). A
  background job queue would be needed for slower providers.
- Similarity-based (semantic) matching is excluded from before/after match scores (see §5).
- PDF rendering is verified on macOS (Homebrew Pango) and in a Linux container. macOS lacks Carlito and
  Caladea, so local PDFs use fallback fonts; production PDFs come from the Linux image
  ([export-qa.md](export-qa.md)).
- CJK characters render as empty boxes in the default Linux image; build with `INSTALL_CJK_FONTS=true` to include Noto CJK (+169 MB). Opt-in by decision in Milestone 8 ([export-qa.md](export-qa.md)); without it, PDFs do not visually support CJK.
- DOCX output has passed structural checks but has **not been opened in Microsoft Word**; see the manual
  checklist in [export-qa.md](export-qa.md).
- Coursework is entered manually; it is not extracted from the uploaded resume.
- The Gemini integration has been reviewed but **not exercised with live calls**; see
  [gemini-verification-plan.md](gemini-verification-plan.md).

## 10. Frontend tests and browser verification (Milestone 6)

- **Automated component tests** (Vitest 4 + React Testing Library, jsdom): `cd frontend && npm test`. The
  backend is faked at the `fetch` boundary (`src/test/fakeApi.js`), so the real API client, components and
  error handling run. Covered: rewrite setup (resume/job selection, scopes, modes, selected bullets,
  loading and errors), suggestion accept/reject and blocked suggestions, regeneration, editing (summary,
  skills, coursework, cancel), verification labels for user edits, version view/restore, stale-version
  conflict, reload after job deletion, template selection and preview, export acknowledgement (per
  version), downloads and export errors, saved-rewrite loading/empty/error/delete, and the shared resume
  and job pickers on both Job match and Rewrite pages.
- **Automated real-browser run** (Milestone 6; since Milestone 7 it lives in `frontend/e2e` and runs in CI, see [frontend.md](frontend.md)): a Playwright script drove Google Chrome against
  `python -m scripts.mock_ai_server` (fake AI provider) and the Vite dev server through registration,
  sign-in, upload, job creation, generation, reject/accept, an unverifiable edit, acknowledgement, PDF and
  DOCX download, all five template previews, version view and restore, job deletion (rewrite kept and
  detached), 390 px and 768 px layouts (no horizontal scroll) and account deletion (all rows removed). No
  JavaScript errors and no 5xx responses. **No manual (human) browser session has been performed.**
- Bugs found and fixed by these tests: saving a summary, skills, education, projects or contact edit
  failed with `transform is not a function` (only role edits worked); comma-separated list fields swallowed
  the comma while typing, so new skills could not be typed; reopening the "Current rewrite" tab showed the
  stale version loaded when the rewrite was first opened.
