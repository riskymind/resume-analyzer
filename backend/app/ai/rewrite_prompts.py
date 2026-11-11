"""Prompt for resume rewriting.

The model sees the resume as JSON items with ids and returns wording only. It
never returns employers, job titles, dates, institutions, qualifications or
certification names; application code copies those from the original. Contact
details (name, email, phone, links, location), employer names, institution
names and grades are not sent at all: the rewrite does not need them.

The resume and job data are untrusted and travel inside fenced tags in the user
content; instructions live only in the system channel.
"""

from __future__ import annotations

import json
from typing import Any

from app.ai.prompts import UNTRUSTED_DATA_RULES, fence

PROMPT_VERSION_REWRITE = "resume-rewrite/1"

MODE_STYLES: dict[str, str] = {
    "professional": (
        "Professional rewrite: improve clarity, grammar, concision and professional tone. Keep the candidate's "
        "voice. Prefer plain, specific language over buzzwords."
    ),
    "ats": (
        "ATS optimisation: use standard, parseable wording. Name tools and skills exactly as the resume names them, "
        "use the job's terminology where the resume already evidences it, avoid symbols, tables and decorative "
        "characters, and keep bullets to one sentence."
    ),
    "job_targeted": (
        "Job-specific rewrite: emphasise the experience that is most relevant to the target job. Address required "
        "qualifications before preferred ones. Work the job's keywords in naturally where the resume already "
        "evidences them; never stuff keywords."
    ),
    "executive": (
        "Executive rewrite: a senior, strategic register. Lead with scope, outcomes and decisions that the resume "
        "actually describes. Concise and confident, without inflating responsibility or seniority."
    ),
}

SECTION_INSTRUCTIONS: dict[str, str] = {
    "summary": '"summary": a 2-4 sentence professional summary built only from facts in the resume.',
    "experience": (
        '"experience": for each role, rewritten bullets. Each bullet cites the original bullet id(s) it rewrites in '
        '"source_ids". You may merge closely related bullets; never create a bullet without a source.'
    ),
    "skills": (
        '"skills": the existing technical and soft skills, reordered so the most relevant come first. Use only '
        "skills already listed; do not add or rename any."
    ),
    "projects": '"projects": a rewritten description for each project, by id.',
    "education": (
        '"education_order" and "certification_order": the ids of the education and certification items in the most '
        "relevant order. You cannot change their content."
    ),
}

REWRITE_SYSTEM = f"""\
TASK: resume-rewrite
You are a careful resume editor. You improve how an existing resume presents the candidate's real experience.
You rephrase, tighten, reorder and emphasise. You never add facts.

The user message contains:
- <resume>: JSON with the resume content. Every item has an "id".
- <job_description>: JSON with the target job's requirements and what the resume does and does not evidence
  (may be absent for a general improvement).
- "request": the sections to return, the rewrite mode and, optionally, the bullet ids to rewrite.

Respond with ONLY one JSON object (no markdown fences, no commentary). Include only the requested sections:
{{
  "summary": {{"text": "...", "keywords": ["..."], "requirement_ids": ["r1"], "rationale": "..."}},
  "experience": [{{"id": "exp-1", "bullets": [{{"text": "...", "source_ids": ["exp-1-b1"], "keywords": ["..."],
                  "requirement_ids": ["r2"], "rationale": "...", "metric_prompt": "..." or null}}]}}],
  "skills": {{"technical": ["..."], "soft": ["..."], "rationale": "..."}},
  "projects": [{{"id": "proj-1", "description": "...", "keywords": ["..."], "requirement_ids": [],
                "rationale": "..."}}],
  "education_order": ["edu-1"], "certification_order": ["cert-1"],
  "alignment_notes": ["<one short sentence on how the rewrite addresses the job>"]
}}

FACTUAL INTEGRITY RULES (these override every style instruction):
1. Do not invent or change employers, job titles, dates, locations, degrees, institutions or certifications.
   They are not part of your output. Refer to items only by their "id".
2. Every number in your text (metrics, percentages, money, team sizes, user counts, durations, years) must
   already appear in the source item(s) you cite, with the same unit and scale. Never add a metric. Never write
   vague quantities such as "dozens", "hundreds", "millions" or "a decade" unless the source says so.
3. Mention only tools, technologies, skills, qualifications and certifications that appear in the resume.
   Requirements listed in "not_evidenced" are gaps: do not mention them anywhere, not even as "familiar with".
4. Do not upgrade a related skill into the required one (experience with Django is not experience with FastAPI).
5. Do not escalate responsibility: do not write that the candidate led, managed, owned, mentored or supervised
   anything unless the source says so. Do not widen scope (company-wide, global) beyond the source.
6. Do not mention the target employer, and do not describe the candidate with the target job title.
7. Do not state or change years of experience unless the resume states them.
8. Each rewritten bullet must cite its source bullet id(s) in "source_ids" from the same role.
9. When a bullet would be stronger with a figure the resume does not give, keep it without a number and add a
   short question for the candidate in "metric_prompt" (for example "How many users did this serve?").
   The question must not contain a number.
10. "keywords" lists only job keywords that literally appear in your text; "requirement_ids" lists only ids of
    requirements your text evidences.

STYLE:
- Start bullets with a strong action verb. Past tense for past roles; present tense for a current role.
- One idea per bullet, normally under 30 words. No first person ("I", "my"). No buzzwords or clichés.
- Preserve every original figure exactly when you keep it.

{UNTRUSTED_DATA_RULES}"""


def build_rewrite_prompt(
    *,
    resume: dict[str, Any],
    job: dict[str, Any] | None,
    sections: list[str],
    mode: str,
    bullet_ids: list[str],
    extra_instructions: list[str] | None = None,
) -> tuple[str, str]:
    """Return ``(system, user_content)``. Both JSON payloads are fenced as untrusted data."""

    request: dict[str, Any] = {
        "sections": sections,
        "mode": mode,
        "style": MODE_STYLES[mode],
    }
    instructions = [SECTION_INSTRUCTIONS[s] for s in sections if s in SECTION_INSTRUCTIONS]
    if bullet_ids:
        request["rewrite_only_bullet_ids"] = bullet_ids
        instructions.append(
            "Rewrite only the listed bullets, one output bullet per listed id, and return no other bullets."
        )
    request["section_instructions"] = instructions + list(extra_instructions or [])
    parts = [
        "Rewrite the following resume.",
        "request: " + json.dumps(request, ensure_ascii=False),
        fence("resume", json.dumps(resume, ensure_ascii=False, indent=1)),
    ]
    if job is not None:
        parts.append(fence("job_description", json.dumps(job, ensure_ascii=False, indent=1)))
    return REWRITE_SYSTEM, "\n\n".join(parts)
